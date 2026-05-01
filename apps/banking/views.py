import json
from datetime import date, timedelta
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods

from .categories import (
    CATEGORY_LABELS, INCOME_CATEGORIES, SPENDING_CATEGORIES, TRANSFER_CATEGORIES,
    UNCATEGORIZED,
)
from .models import Account, Institution, Transaction
from .services import income_expense_summary, link_institution, set_category as set_category_service, spending_breakdown, sync_institution


def _page_window(current: int, total: int, edge: int = 1, around: int = 2) -> list[int | None]:
    """Numbered-pagination window. Always shows pages 1..edge, total-edge+1..total, and current ± around. None entries are ellipsis gaps."""
    if total <= edge * 2 + around * 2 + 1:
        return list(range(1, total + 1))
    pages = set(range(1, edge + 1))
    pages.update(range(total - edge + 1, total + 1))
    pages.update(range(max(1, current - around), min(total, current + around) + 1))
    out: list[int | None] = []
    prev = 0
    for p in sorted(pages):
        if p > prev + 1:
            out.append(None)
        out.append(p)
        prev = p
    return out


def _safe_url(url: str, request, default: str) -> str:
    """Return `url` if it's same-origin and valid; otherwise `default`. Used to
    validate user-supplied 'next' params or Referer headers without enabling
    open-redirects."""
    if url and url_has_allowed_host_and_scheme(
        url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return url
    return default


def _safe_back(request, default: str) -> str:
    """Return the Referer URL if it's same-origin, else `default`."""
    return _safe_url(request.META.get("HTTP_REFERER", ""), request, default)


def _filtered_transactions_qs(user, params):
    """Apply the same filter set as the transactions_list view to a Transaction queryset
    scoped to a user. `params` is a request.GET or request.POST dict-like.
    Returns the filtered queryset (no pagination). Used by both transactions_list
    and bulk_set_category_by_filter."""
    qs = (
        Transaction.objects
        .filter(account__institution__user=user)
        .select_related("account", "account__institution")
        .order_by("-posted_at", "-id")
    )

    account_id = params.get("account")
    if account_id and account_id.isdigit():
        qs = qs.filter(account_id=int(account_id))

    preset = params.get("range", "")
    today = timezone.localdate()
    if preset == "30d":
        qs = qs.filter(posted_at__gte=today - timedelta(days=30))
    elif preset == "90d":
        qs = qs.filter(posted_at__gte=today - timedelta(days=90))
    elif preset == "ytd":
        qs = qs.filter(posted_at__gte=today.replace(month=1, day=1))
    elif preset == "1y":
        qs = qs.filter(posted_at__gte=today - timedelta(days=365))

    search = (params.get("q") or "").strip()
    if search:
        qs = qs.filter(
            Q(display_name__icontains=search)
            | Q(payee__icontains=search)
            | Q(description__icontains=search)
            | Q(memo__icontains=search)
        )

    selected_category = (params.get("category") or "").strip()
    if selected_category:
        qs = qs.filter(category=selected_category)

    return qs


@login_required
def banks_list(request):
    accounts = (
        Account.objects
        .for_user(request.user)
        .filter(type__in=["checking", "savings", "other"])
        .select_related("institution")
        .order_by("institution__display_name", "institution__name", "display_name", "name")
    )
    return render(request, "banking/banks_list.html", {"accounts": accounts})


@login_required
def link_form(request):
    """Provider chooser. Routes to /banking/link/simplefin/ or /banking/link/teller/."""
    return render(request, "banking/link_chooser.html", {})


@login_required
@require_http_methods(["GET", "POST"])
def link_form_simplefin(request):
    if request.method == "POST":
        setup_token = request.POST.get("setup_token", "").strip()
        display_name = request.POST.get("display_name", "").strip() or "SimpleFIN Account"
        if not setup_token:
            messages.error(request, "Setup token is required.")
            return render(request, "banking/link_form.html", {})
        try:
            link_institution(user=request.user, setup_token=setup_token, display_name=display_name)
        except Exception as exc:
            messages.error(request, f"Link failed: {exc}")
            return render(request, "banking/link_form.html", {"display_name": display_name})
        messages.success(request, "Institution linked. Initial sync complete.")
        return HttpResponseRedirect(reverse("banking:list"))
    return render(request, "banking/link_form.html", {})


@login_required
def link_form_teller(request):
    return render(request, "banking/link_form_teller.html", {
        "teller_application_id": settings.TELLER_APPLICATION_ID,
        "teller_environment": settings.TELLER_ENVIRONMENT,
    })


@login_required
@require_http_methods(["POST"])
def link_form_teller_callback(request):
    """Receives JSON {access_token, display_name} from the Teller Connect onSuccess
    callback. Validates and links the institution; returns JSON for the JS to consume."""
    try:
        body = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "Invalid JSON body."}, status=400)

    access_token = (body.get("access_token") or "").strip()
    display_name = (body.get("display_name") or "").strip() or "Teller Account"
    if not access_token:
        return JsonResponse({"ok": False, "error": "access_token is required."}, status=400)

    try:
        link_institution(
            user=request.user,
            setup_token=access_token,
            display_name=display_name,
            provider_name="teller",
        )
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)

    return JsonResponse({"ok": True, "redirect_url": reverse("banking:list")})


@login_required
@require_http_methods(["POST"])
def sync_institution_view(request, institution_id):
    institution = get_object_or_404(Institution.objects.for_user(request.user), pk=institution_id)
    try:
        result = sync_institution(institution)
    except Exception as exc:
        messages.error(request, f"Sync failed: {exc}")
    else:
        messages.success(
            request,
            f"Synced {result.accounts_created + result.accounts_updated} accounts "
            f"({result.transactions_created} new transactions).",
        )
    return HttpResponseRedirect(reverse("banking:list"))


@login_required
def account_detail(request, account_id):
    account = get_object_or_404(Account.objects.for_user(request.user), pk=account_id)
    transactions = (
        Transaction.objects
        .filter(account=account)
        .order_by("-posted_at", "-id")[:500]
    )
    return render(request, "banking/account_detail.html", {
        "account": account,
        "transactions": transactions,
    })


@login_required
@require_http_methods(["GET", "POST"])
def rename_institution(request, institution_id):
    institution = get_object_or_404(Institution.objects.for_user(request.user), pk=institution_id)
    if request.method == "POST":
        institution.display_name = request.POST.get("display_name", "").strip()
        institution.save(update_fields=["display_name"])
        messages.success(request, f"Renamed to \"{institution.effective_name}\".")
        return HttpResponseRedirect(reverse("banking:list"))
    return render(request, "banking/rename_form.html", {
        "subject": "institution",
        "object": institution,
        "cancel_url": reverse("banking:list"),
        "current_value": institution.display_name,
        "fallback_value": institution.name,
    })


@login_required
@require_http_methods(["GET", "POST"])
def rename_account(request, account_id):
    account = get_object_or_404(Account.objects.for_user(request.user), pk=account_id)
    if request.method == "POST":
        account.display_name = request.POST.get("display_name", "").strip()
        account.save(update_fields=["display_name"])
        messages.success(request, f"Renamed to \"{account.effective_name}\".")
        return HttpResponseRedirect(reverse("banking:account_detail", args=[account.id]))
    return render(request, "banking/rename_form.html", {
        "subject": "account",
        "object": account,
        "cancel_url": reverse("banking:account_detail", args=[account.id]),
        "current_value": account.display_name,
        "fallback_value": account.name,
    })


@login_required
@require_http_methods(["GET", "POST"])
def rename_transaction(request, transaction_id):
    transaction = get_object_or_404(
        Transaction.objects.for_user(request.user), pk=transaction_id
    )
    fallback = transaction.payee or transaction.description
    default_redirect = reverse("transactions")
    if request.method == "POST":
        transaction.display_name = request.POST.get("display_name", "").strip()
        transaction.save(update_fields=["display_name"])
        messages.success(request, f'Renamed to "{transaction.effective_payee}".')
        return HttpResponseRedirect(_safe_url(request.POST.get("next", ""), request, default_redirect))
    back_url = _safe_back(request, default=default_redirect)
    return render(request, "banking/rename_form.html", {
        "subject": "transaction",
        "object": transaction,
        "cancel_url": back_url,
        "back_url": back_url,
        "current_value": transaction.display_name,
        "fallback_value": fallback,
    })


@login_required
@require_http_methods(["GET", "POST"])
def delete_institution(request, institution_id):
    institution = get_object_or_404(Institution.objects.for_user(request.user), pk=institution_id)
    if request.method == "POST":
        name = institution.effective_name
        institution.delete()
        messages.success(request, f"Deleted {name} and all related accounts/transactions.")
        return HttpResponseRedirect(reverse("banking:list"))
    return render(request, "banking/institution_confirm_delete.html", {"institution": institution})


@login_required
@require_http_methods(["GET", "POST"])
def delete_account(request, account_id):
    account = get_object_or_404(Account.objects.for_user(request.user), pk=account_id)
    if request.method == "POST":
        name = account.effective_name
        account.delete()
        messages.success(request, f"Deleted {name} and its transactions.")
        return HttpResponseRedirect(reverse("banking:list"))
    return render(request, "banking/account_confirm_delete.html", {"account": account})


@login_required
def transactions_list(request):
    qs = _filtered_transactions_qs(request.user, request.GET)

    # Re-extract the filter values for template context (the helper consumed them
    # but we need them back to render the filter bar with selected values).
    account_id = request.GET.get("account")
    selected_account = int(account_id) if account_id and account_id.isdigit() else None
    preset = request.GET.get("range", "")
    search = (request.GET.get("q") or "").strip()
    selected_category = (request.GET.get("category") or "").strip()

    # Top 5 spending categories by transaction count for this user (for filter pills).
    top_categories = list(
        Transaction.objects.for_user(request.user)
        .filter(category__in=SPENDING_CATEGORIES)
        .values("category")
        .annotate(n=Count("id"))
        .order_by("-n")
        .values_list("category", flat=True)[:5]
    )
    if not top_categories:
        top_categories = ["groceries", "dining", "transportation", "utilities", "shopping"]

    other_categories = [
        c for c in (SPENDING_CATEGORIES + INCOME_CATEGORIES + TRANSFER_CATEGORIES + [UNCATEGORIZED])
        if c not in top_categories
    ]

    paginator = Paginator(qs, 50)
    page_obj = paginator.get_page(request.GET.get("page"))

    accounts = Account.objects.for_user(request.user).order_by("institution__name", "name")

    # Pre-compute the filter query string so each page link doesn't have to rebuild it
    qs_params: dict[str, object] = {}
    if account_id and account_id.isdigit():
        qs_params["account"] = int(account_id)
    if preset:
        qs_params["range"] = preset
    if search:
        qs_params["q"] = search
    if selected_category:
        qs_params["category"] = selected_category
    filter_qs = urlencode(qs_params)

    has_any_filter = bool(selected_account or preset or search or selected_category)
    filtered_count = paginator.count if has_any_filter else 0

    return render(request, "banking/transactions_list.html", {
        "page_obj": page_obj,
        "accounts": accounts,
        "selected_account": selected_account,
        "selected_range": preset,
        "search": search,
        "filter_qs": filter_qs,
        "page_window": _page_window(page_obj.number, paginator.num_pages),
        "selected_category": selected_category,
        "top_categories": top_categories,
        "other_categories": other_categories,
        "category_labels": CATEGORY_LABELS,
        "has_any_filter": has_any_filter,
        "filtered_count": filtered_count,
    })


@login_required
@require_http_methods(["POST"])
def set_category(request, transaction_id):
    tx = get_object_or_404(
        Transaction.objects.for_user(request.user), pk=transaction_id,
    )
    category = request.POST.get("category", "").strip()
    try:
        set_category_service(tx, category)
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))
    from .templatetags.category_tags import category_pill_html
    return HttpResponse(category_pill_html(tx.category))


@login_required
@require_http_methods(["POST"])
def bulk_set_category(request):
    """Set the same category on a list of transactions in one shot.
    Accepts: POST with `category` (string) and `transaction_ids` (list of ints).
    Returns JSON {"updated": N} where N is the number of rows actually updated."""
    from .categories import ALL_CATEGORIES
    category = (request.POST.get("category") or "").strip()
    if category not in ALL_CATEGORIES:
        return HttpResponseBadRequest(f"Invalid category: {category}")
    raw_ids = request.POST.getlist("transaction_ids")
    if not raw_ids:
        return HttpResponseBadRequest("No transactions selected.")
    try:
        ids = [int(x) for x in raw_ids]
    except (TypeError, ValueError):
        return HttpResponseBadRequest("Invalid transaction id.")
    qs = Transaction.objects.for_user(request.user).filter(id__in=ids)
    count = qs.update(category=category, category_manual=True)
    return JsonResponse({"updated": count})


def _spending_window(period: str, month_param: str | None = None):
    """Parse the ?period= and ?month=YYYY-MM query values into context.

    Returns a dict with: start, end, label, period (echoed),
    prev_month (str YYYY-MM or None), next_month (str YYYY-MM or None).
    Only returns prev/next for the 'month' period; otherwise both are None.
    """
    today = date.today()

    if period == "30d":
        return {
            "start": today - timedelta(days=29), "end": today,
            "label": "Last 30 days", "period": "30d",
            "prev_month": None, "next_month": None,
        }

    if period == "ytd":
        return {
            "start": date(today.year, 1, 1), "end": today,
            "label": f"{today.year} YTD", "period": "ytd",
            "prev_month": None, "next_month": None,
        }

    # period == "month" (default)
    target_year, target_month = today.year, today.month
    if month_param:
        try:
            year_str, month_str = month_param.split("-", 1)
            y, m = int(year_str), int(month_str)
            if 1 <= m <= 12 and 1900 <= y <= 9999:
                target_year, target_month = y, m
        except (ValueError, AttributeError):
            pass  # bad input → fall back to current month

    start = date(target_year, target_month, 1)
    # End of month: last day. Compute as first-of-next-month minus one day.
    if target_month == 12:
        next_first = date(target_year + 1, 1, 1)
    else:
        next_first = date(target_year, target_month + 1, 1)
    end = next_first - timedelta(days=1)
    # If the target month is the current month, cap end at today (so partial-month totals don't double-count
    # transactions far in the future that may have been pre-dated).
    if target_year == today.year and target_month == today.month:
        end = today

    label = start.strftime("%B %Y")

    # Previous month
    if target_month == 1:
        prev_y, prev_m = target_year - 1, 12
    else:
        prev_y, prev_m = target_year, target_month - 1
    prev_month = f"{prev_y:04d}-{prev_m:02d}"

    # Next month — None if we're already at the current month (no forward navigation past now).
    is_current = (target_year == today.year and target_month == today.month)
    if is_current:
        next_month = None
    else:
        if target_month == 12:
            next_y, next_m = target_year + 1, 1
        else:
            next_y, next_m = target_year, target_month + 1
        next_month = f"{next_y:04d}-{next_m:02d}"

    return {
        "start": start, "end": end,
        "label": label, "period": "month",
        "prev_month": prev_month, "next_month": next_month,
    }


@login_required
def spending(request):
    period = request.GET.get("period", "month")
    month_param = request.GET.get("month")
    window = _spending_window(period, month_param)
    breakdown = spending_breakdown(request.user, window["start"], window["end"], include_transfers=True)
    income_total, expense_total = income_expense_summary(request.user, window["start"], window["end"])
    return render(request, "banking/spending.html", {
        "rows": breakdown,
        "income_total": income_total,
        "expense_total": expense_total,
        "net": income_total - expense_total,
        "period": window["period"],
        "period_label": window["label"],
        "prev_month": window["prev_month"],
        "next_month": window["next_month"],
    })


@login_required
@require_http_methods(["POST"])
def bulk_set_category_by_filter(request):
    """Set the same category on every transaction matching the filter params.
    Accepts: POST with `target_category` (string) and the same filter keys as
    transactions_list (account, range, q, category).
    Returns JSON {"updated": N}."""
    from .categories import ALL_CATEGORIES
    target_category = (request.POST.get("target_category") or "").strip()
    if target_category not in ALL_CATEGORIES:
        return HttpResponseBadRequest(f"Invalid target category: {target_category}")
    qs = _filtered_transactions_qs(request.user, request.POST)
    count = qs.update(category=target_category, category_manual=True)
    return JsonResponse({"updated": count})
