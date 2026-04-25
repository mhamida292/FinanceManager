from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from .models import Account, Institution, Transaction
from .services import link_institution, sync_institution


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
    today = date.today()
    if preset == "30d":
        qs = qs.filter(posted_at__gte=today - timedelta(days=30))
    elif preset == "90d":
        qs = qs.filter(posted_at__gte=today - timedelta(days=90))
    elif preset == "ytd":
        qs = qs.filter(posted_at__gte=date(today.year, 1, 1))
    elif preset == "1y":
        qs = qs.filter(posted_at__gte=today - timedelta(days=365))

    search = (request.GET.get("q") or "").strip()
    if search:
        qs = qs.filter(Q(payee__icontains=search) | Q(description__icontains=search) | Q(memo__icontains=search))

    paginator = Paginator(qs, 50)
    page_obj = paginator.get_page(request.GET.get("page"))

    accounts = Account.objects.for_user(request.user).order_by("institution__name", "name")

    return render(request, "banking/transactions_list.html", {
        "page_obj": page_obj,
        "accounts": accounts,
        "selected_account": int(account_id) if account_id and account_id.isdigit() else None,
        "selected_range": preset,
        "search": search,
    })
