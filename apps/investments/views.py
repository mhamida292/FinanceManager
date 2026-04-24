from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from apps.banking.models import Institution

from .models import Holding, InvestmentAccount
from .services import (
    create_manual_account, refresh_manual_prices, sync_simplefin_investments,
    update_cost_basis, upsert_manual_holding,
)


def _decimal_or_none(raw: str) -> Decimal | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        raise ValueError(f"Not a valid number: {raw!r}")


@login_required
def investments_list(request):
    accounts = (
        InvestmentAccount.objects
        .for_user(request.user)
        .prefetch_related("holdings")
    )
    grand_total = Decimal("0")
    for acc in accounts:
        grand_total += sum((h.market_value for h in acc.holdings.all()), Decimal("0"))
    return render(request, "investments/investments_list.html", {
        "accounts": accounts,
        "grand_total": grand_total,
    })


@login_required
def account_detail(request, account_id):
    account = get_object_or_404(InvestmentAccount.objects.for_user(request.user), pk=account_id)
    holdings = account.holdings.all().order_by("symbol")
    total_value = sum((h.market_value for h in holdings), Decimal("0"))
    total_cost = sum((h.cost_basis or Decimal("0") for h in holdings), Decimal("0"))
    total_gain = total_value - total_cost if total_cost else None
    return render(request, "investments/account_detail.html", {
        "account": account,
        "holdings": holdings,
        "total_value": total_value,
        "total_cost": total_cost,
        "total_gain": total_gain,
    })


@login_required
@require_http_methods(["GET", "POST"])
def add_manual_account(request):
    if request.method == "POST":
        broker = request.POST.get("broker", "").strip()
        name = request.POST.get("name", "").strip()
        notes = request.POST.get("notes", "").strip()
        if not name:
            messages.error(request, "Account name is required.")
            return render(request, "investments/add_account_form.html", {"broker": broker, "name": name, "notes": notes})
        acc = create_manual_account(user=request.user, broker=broker, name=name, notes=notes)
        messages.success(request, f"Created {acc.effective_name}.")
        return HttpResponseRedirect(reverse("investments:account_detail", args=[acc.id]))
    return render(request, "investments/add_account_form.html", {})


@login_required
@require_http_methods(["GET", "POST"])
def add_holding(request, account_id):
    account = get_object_or_404(InvestmentAccount.objects.for_user(request.user), pk=account_id, source="manual")
    if request.method == "POST":
        symbol = request.POST.get("symbol", "").strip().upper()
        try:
            shares = _decimal_or_none(request.POST.get("shares", ""))
            cost_basis = _decimal_or_none(request.POST.get("cost_basis", ""))
        except ValueError as exc:
            messages.error(request, str(exc))
            return render(request, "investments/add_holding_form.html", {"account": account, **request.POST.dict()})
        if not symbol or shares is None:
            messages.error(request, "Symbol and shares are required.")
            return render(request, "investments/add_holding_form.html", {"account": account, **request.POST.dict()})
        upsert_manual_holding(investment_account=account, symbol=symbol, shares=shares, cost_basis=cost_basis)
        # Auto-fetch the price right away so the user doesn't have to remember to click refresh.
        try:
            refresh_manual_prices(user=request.user)
            messages.success(request, f"Added {symbol} × {shares}. Price refresh ran.")
        except Exception as exc:
            messages.warning(
                request,
                f"Added {symbol} × {shares}, but price refresh failed: {exc}. Click ⟳ Refresh prices to retry.",
            )
        return HttpResponseRedirect(reverse("investments:account_detail", args=[account.id]))
    return render(request, "investments/add_holding_form.html", {"account": account})


@login_required
@require_http_methods(["GET", "POST"])
def edit_holding(request, holding_id):
    holding = get_object_or_404(Holding.objects.for_user(request.user), pk=holding_id)
    account = holding.investment_account
    if request.method == "POST":
        try:
            cost_basis = _decimal_or_none(request.POST.get("cost_basis", ""))
        except ValueError as exc:
            messages.error(request, str(exc))
            return render(request, "investments/edit_holding_form.html", {"holding": holding})
        if account.source == "manual":
            try:
                shares = _decimal_or_none(request.POST.get("shares", ""))
            except ValueError as exc:
                messages.error(request, str(exc))
                return render(request, "investments/edit_holding_form.html", {"holding": holding})
            if shares is not None:
                holding.shares = shares
                holding.recompute_market_value()
                holding.save(update_fields=["shares", "market_value"])
        update_cost_basis(holding=holding, cost_basis=cost_basis)
        messages.success(request, f"Updated {holding.symbol}.")
        return HttpResponseRedirect(reverse("investments:account_detail", args=[account.id]))
    return render(request, "investments/edit_holding_form.html", {"holding": holding})


@login_required
@require_http_methods(["POST"])
def refresh_prices(request):
    updated = refresh_manual_prices(user=request.user)
    messages.success(request, f"Refreshed prices for {updated} manual holding(s).")
    return HttpResponseRedirect(reverse("investments:list"))


@login_required
@require_http_methods(["POST"])
def sync_investments_view(request, institution_id):
    institution = get_object_or_404(Institution.objects.for_user(request.user), pk=institution_id)
    try:
        result = sync_simplefin_investments(institution)
    except Exception as exc:
        messages.error(request, f"Investment sync failed: {exc}")
    else:
        messages.success(
            request,
            f"Synced {result.accounts_created + result.accounts_updated} brokerage account(s), "
            f"{result.holdings_created} new holdings.",
        )
    return HttpResponseRedirect(reverse("investments:list"))


@login_required
@require_http_methods(["GET", "POST"])
def delete_account(request, account_id):
    account = get_object_or_404(InvestmentAccount.objects.for_user(request.user), pk=account_id)
    if request.method == "POST":
        name = account.effective_name
        account.delete()
        messages.success(request, f"Deleted {name} and its holdings.")
        return HttpResponseRedirect(reverse("investments:list"))
    return render(request, "investments/account_confirm_delete.html", {"account": account})
