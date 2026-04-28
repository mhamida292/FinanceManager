from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.providers.registry import get as get_provider

from .models import Account, Institution, Transaction


@dataclass
class SyncResult:
    institution: Institution
    accounts_created: int
    accounts_updated: int
    transactions_created: int
    transactions_updated: int


def link_institution(*, user, setup_token: str, display_name: str, provider_name: str = "simplefin") -> Institution:
    """Exchange a setup token for an access URL, store it, and do an initial sync."""
    provider = get_provider(provider_name)
    access_url = provider.exchange_setup_token(setup_token)
    institution = Institution.objects.create(
        user=user,
        name=display_name,
        provider=provider_name,
        access_url=access_url,
    )
    sync_institution(institution)
    return institution


def sync_institution(institution: Institution) -> SyncResult:
    """Fetch fresh data from the provider and upsert accounts + transactions."""
    provider = get_provider(institution.provider)

    # 30-day overlap on incremental syncs catches late-posting transactions and
    # reconciles pending → posted transitions. None on first sync = full backfill.
    since = None
    if institution.last_synced_at is not None:
        since = institution.last_synced_at - timedelta(days=30)

    accounts_created = accounts_updated = 0
    transactions_created = transactions_updated = 0

    with transaction.atomic():
        for payload in provider.fetch_accounts_with_transactions(
            institution.access_url, since=since,
        ):
            # Type is set on initial create from the provider's heuristic guess.
            # On update we PRESERVE the existing type — if a user reclassified an
            # account in the admin (e.g. "Other" → "Credit Card"), sync must not
            # clobber that. Same lock pattern as Holding.cost_basis_source=manual.
            existing = Account.objects.filter(
                institution=institution, external_id=payload.account.external_id,
            ).first()
            update_fields = {
                "name": payload.account.name,
                "balance": payload.account.balance,
                "currency": payload.account.currency,
                "org_name": payload.account.org_name,
                "last_synced_at": timezone.now(),
            }
            if existing is None:
                acc = Account.objects.create(
                    institution=institution,
                    external_id=payload.account.external_id,
                    type=payload.account.type,
                    **update_fields,
                )
                acc_created = True
            else:
                for field, value in update_fields.items():
                    setattr(existing, field, value)
                existing.save()
                acc = existing
                acc_created = False

            if acc_created:
                accounts_created += 1
            else:
                accounts_updated += 1

            for tx in payload.transactions:
                _, tx_created = Transaction.objects.update_or_create(
                    account=acc,
                    external_id=tx.external_id,
                    defaults={
                        "posted_at": tx.posted_at,
                        "amount": tx.amount,
                        "description": tx.description,
                        "payee": tx.payee,
                        "memo": tx.memo,
                        "pending": tx.pending,
                    },
                )
                if tx_created:
                    transactions_created += 1
                else:
                    transactions_updated += 1

        institution.last_synced_at = timezone.now()
        institution.save(update_fields=["last_synced_at"])

    return SyncResult(
        institution=institution,
        accounts_created=accounts_created,
        accounts_updated=accounts_updated,
        transactions_created=transactions_created,
        transactions_updated=transactions_updated,
    )
