from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.providers.registry import get as get_provider

from .categories import map_teller_category
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
                mapped_category = map_teller_category(tx.provider_category)
                defaults = {
                    "posted_at": tx.posted_at,
                    "amount": tx.amount,
                    "description": tx.description,
                    "payee": tx.payee,
                    "memo": tx.memo,
                    "pending": tx.pending,
                }
                existing_tx = Transaction.objects.filter(
                    account=acc, external_id=tx.external_id,
                ).first()
                if existing_tx is None:
                    Transaction.objects.create(
                        account=acc, external_id=tx.external_id,
                        category=mapped_category,
                        category_manual=False,
                        **defaults,
                    )
                    transactions_created += 1
                else:
                    for field, value in defaults.items():
                        setattr(existing_tx, field, value)
                    # Only re-apply mapped category if user has not overridden it.
                    if not existing_tx.category_manual:
                        existing_tx.category = mapped_category
                    existing_tx.save()
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


from dataclasses import dataclass as _dc
from datetime import date as _date
from decimal import Decimal as _Decimal

from .categories import (
    ALL_CATEGORIES, CATEGORY_COLORS, CATEGORY_LABELS, INCOME_CATEGORIES, SPENDING_CATEGORIES,
    TRANSFER_CATEGORIES, UNCATEGORIZED,
)


@_dc(frozen=True)
class CategoryTotal:
    category: str
    label: str
    color: str
    total: _Decimal       # absolute value of money flowing out, always >= 0
    percent: float        # share of total spending


def _date_to_aware_range(start: _date, end: _date):
    """Convert (start, end) dates to a [start_dt, end_dt) datetime range covering both endpoints inclusive."""
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    start_dt = _dt.combine(start, _dt.min.time(), tzinfo=_tz.utc)
    end_dt = _dt.combine(end + _td(days=1), _dt.min.time(), tzinfo=_tz.utc)
    return start_dt, end_dt


def spending_breakdown(user, start: _date, end: _date) -> list[CategoryTotal]:
    """Per-category spending totals for the inclusive [start, end] date range.
    Excludes income and transfer. Includes 'uncategorized' as a slice (muted).
    Sorted descending by total. Uses Transaction.display_amount to respect
    credit/loan sign-flipping."""
    start_dt, end_dt = _date_to_aware_range(start, end)
    qs = (
        Transaction.objects.for_user(user)
        .filter(posted_at__gte=start_dt, posted_at__lt=end_dt)
        .exclude(category__in=INCOME_CATEGORIES + TRANSFER_CATEGORIES)
        .select_related("account")
    )

    totals: dict[str, _Decimal] = {}
    for tx in qs:
        amt = tx.display_amount
        if amt >= 0:
            continue  # not a spend (e.g., refund) — exclude from breakdown
        totals[tx.category] = totals.get(tx.category, _Decimal("0")) + (-amt)

    grand = sum(totals.values(), _Decimal("0"))
    rows = [
        CategoryTotal(
            category=cat,
            label=CATEGORY_LABELS[cat],
            color=CATEGORY_COLORS[cat],
            total=total,
            percent=float(total / grand * 100) if grand > 0 else 0.0,
        )
        for cat, total in totals.items()
    ]
    rows.sort(key=lambda r: r.total, reverse=True)
    return rows


def income_expense_summary(user, start: _date, end: _date) -> tuple[_Decimal, _Decimal]:
    """Return (income_total, expense_total) for the inclusive [start, end] range.
    income_total = sum of display_amount where category in INCOME_CATEGORIES.
    expense_total = abs(sum) of display_amount over SPENDING + UNCATEGORIZED rows
    where display_amount < 0. Transfers excluded from both."""
    start_dt, end_dt = _date_to_aware_range(start, end)
    qs = (
        Transaction.objects.for_user(user)
        .filter(posted_at__gte=start_dt, posted_at__lt=end_dt)
        .exclude(category__in=TRANSFER_CATEGORIES)
        .select_related("account")
    )
    income = _Decimal("0")
    expense = _Decimal("0")
    for tx in qs:
        amt = tx.display_amount
        if tx.category in INCOME_CATEGORIES:
            if amt > 0:
                income += amt
        elif amt < 0:
            expense += -amt
    return income, expense


def set_category(transaction: "Transaction", category: str) -> "Transaction":
    """Set the category on a transaction and flag it as user-overridden.
    Raises ValueError if `category` is not a valid category key."""
    if category not in ALL_CATEGORIES:
        raise ValueError(f"Unknown category: {category}")
    transaction.category = category
    transaction.category_manual = True
    transaction.save(update_fields=["category", "category_manual"])
    return transaction
