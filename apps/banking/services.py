from dataclasses import dataclass

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

    accounts_created = accounts_updated = 0
    transactions_created = transactions_updated = 0

    with transaction.atomic():
        for payload in provider.fetch_accounts_with_transactions(institution.access_url):
            acc, acc_created = Account.objects.update_or_create(
                institution=institution,
                external_id=payload.account.external_id,
                defaults={
                    "name": payload.account.name,
                    "type": payload.account.type,
                    "balance": payload.account.balance,
                    "currency": payload.account.currency,
                    "org_name": payload.account.org_name,
                    "last_synced_at": timezone.now(),
                },
            )
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
