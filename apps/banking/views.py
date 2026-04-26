from datetime import timedelta
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods

from .models import Account, Institution, Transaction
from .services import link_institution, sync_institution


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


@login_required
def banks_list(request):
    accounts = (
        Account.objects
        .for_user(request.user)
        .select_related("institution")
        .order_by("institution__display_name", "institution__name", "display_name", "name")
    )
    return render(request, "banking/banks_list.html", {"accounts": accounts})


@login_required
@require_http_methods(["GET", "POST"])
def link_form(request):
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
    qs = (
        Transaction.objects
        .filter(account__institution__user=request.user)
        .select_related("account", "account__institution")
        .order_by("-posted_at", "-id")
    )

    # Filters
    account_id = request.GET.get("account")
    if account_id and account_id.isdigit():
        qs = qs.filter(account_id=int(account_id))

    preset = request.GET.get("range", "")
    today = timezone.localdate()
    if preset == "30d":
        qs = qs.filter(posted_at__gte=today - timedelta(days=30))
    elif preset == "90d":
        qs = qs.filter(posted_at__gte=today - timedelta(days=90))
    elif preset == "ytd":
        qs = qs.filter(posted_at__gte=today.replace(month=1, day=1))
    elif preset == "1y":
        qs = qs.filter(posted_at__gte=today - timedelta(days=365))

    search = (request.GET.get("q") or "").strip()
    if search:
        qs = qs.filter(
            Q(display_name__icontains=search)
            | Q(payee__icontains=search)
            | Q(description__icontains=search)
            | Q(memo__icontains=search)
        )

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
    filter_qs = urlencode(qs_params)

    return render(request, "banking/transactions_list.html", {
        "page_obj": page_obj,
        "accounts": accounts,
        "selected_account": int(account_id) if account_id and account_id.isdigit() else None,
        "selected_range": preset,
        "search": search,
        "filter_qs": filter_qs,
        "page_window": _page_window(page_obj.number, paginator.num_pages),
    })
