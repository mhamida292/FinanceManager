from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Prefetch
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
        .prefetch_related(Prefetch("holdings", queryset=Holding.objects.order_by("symbol")))
        .order_by("broker", "name")
    )
    sections = []
    portfolio_value = Decimal("0")
    portfolio_cost = Decimal("0")
    for acc in accounts:
        holdings = list(acc.holdings.all())  # already ordered by the Prefetch
        holdings_value = sum((h.market_value for h in holdings), Decimal("0"))
        holdings_cost = sum((h.cost_basis or Decimal("0") for h in holdings), Decimal("0"))
        section_total = holdings_value + acc.cash_balance
        section_gain = (holdings_value - holdings_cost) if holdings_cost else None
        section_gain_pct = (section_gain / holdings_cost * 100) if section_gain is not None and holdings_cost else None
        sections.append({
            "account": acc,
            "holdings": holdings,
            "holdings_value": holdings_value,
            "section_total": section_total,
            "section_gain": section_gain,
            "section_gain_pct": section_gain_pct,
        })
        portfolio_value += section_total
        portfolio_cost += holdings_cost
    portfolio_holdings_value = sum((s["holdings_value"] for s in sections), Decimal("0"))
    portfolio_gain = (portfolio_holdings_value - portfolio_cost) if portfolio_cost else None
    portfolio_gain_pct = (portfolio_gain / portfolio_cost * 100) if portfolio_gain is not None and portfolio_cost else None
    return render(request, "investments/investments_list.html", {
        "sections": sections,
        "portfolio_value": portfolio_value,
        "portfolio_gain": portfolio_gain,
        "portfolio_gain_pct": portfolio_gain_pct,
    })


@login_required
def account_detail(request, account_id):
    account = get_object_or_404(InvestmentAccount.objects.for_user(request.user), pk=account_id)
    holdings = account.holdings.all().order_by("symbol")
    holdings_value = sum((h.market_value for h in holdings), Decimal("0"))
    total_value = holdings_value + account.cash_balance
    total_cost = sum((h.cost_basis or Decimal("0") for h in holdings), Decimal("0"))
    total_gain = total_value - total_cost if total_cost else None
    return render(request, "investments/account_detail.html", {
        "account": account,
        "holdings": holdings,
        "holdings_value": holdings_value,
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
        symbols = request.POST.getlist("symbol")
        shares_list = request.POST.getlist("shares")
        cost_basis_list = request.POST.getlist("cost_basis")

        rows = list(zip(symbols, shares_list, cost_basis_list))
        added: list[str] = []
        errors: list[str] = []

        for idx, (symbol_raw, shares_raw, cost_raw) in enumerate(rows, start=1):
            symbol = symbol_raw.strip().upper()
            shares_str = shares_raw.strip()
            cost_str = cost_raw.strip()

            if not symbol and not shares_str and not cost_str:
                continue  # blank row — skip silently

            if not symbol or not shares_str:
                errors.append(f"Row {idx}: symbol and shares are required.")
                continue

            try:
                shares = _decimal_or_none(shares_str)
                cost_basis = _decimal_or_none(cost_str)
            except ValueError as exc:
                errors.append(f"Row {idx} ({symbol}): {exc}")
                continue

            upsert_manual_holding(
                investment_account=account, symbol=symbol, shares=shares, cost_basis=cost_basis,
            )
            added.append(f"{symbol} × {shares}")

        if errors:
            for err in errors:
                messages.error(request, err)
            return render(request, "investments/add_holding_form.html", {
                "account": account,
                "rows": rows,
            })

        if not added:
            messages.error(request, "No rows submitted.")
            return render(request, "investments/add_holding_form.html", {
                "account": account,
                "rows": rows or [("", "", "")] * 5,
            })

        try:
            refresh_manual_prices(user=request.user)
            messages.success(request, f"Added {len(added)} holding(s): {', '.join(added)}. Price refresh ran.")
        except Exception as exc:
            messages.warning(
                request,
                f"Added {len(added)} holding(s), but price refresh failed: {exc}. Click ⟳ Refresh prices to retry.",
            )
        return HttpResponseRedirect(reverse("investments:account_detail", args=[account.id]))
    return render(request, "investments/add_holding_form.html", {
        "account": account,
        "rows": [("", "", "")] * 5,
    })


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


@login_required
@require_http_methods(["GET", "POST"])
def edit_account(request, account_id):
    account = get_object_or_404(InvestmentAccount.objects.for_user(request.user), pk=account_id)
    if request.method == "POST":
        account.name = request.POST.get("name", "").strip() or account.name
        account.broker = request.POST.get("broker", "").strip()
        account.notes = request.POST.get("notes", "").strip()
        try:
            account.cash_balance = _decimal_or_none(request.POST.get("cash_balance", "")) or Decimal("0")
        except ValueError as exc:
            messages.error(request, str(exc))
            return render(request, "investments/edit_account_form.html", {"account": account, "data": request.POST})
        account.save()
        messages.success(request, f"Updated {account.effective_name}.")
        return HttpResponseRedirect(reverse("investments:account_detail", args=[account.id]))
    return render(request, "investments/edit_account_form.html", {"account": account, "data": {
        "name": account.name, "broker": account.broker, "notes": account.notes,
        "cash_balance": account.cash_balance,
    }})


@login_required
@require_http_methods(["GET", "POST"])
def rename_investment_account(request, account_id):
    account = get_object_or_404(
        InvestmentAccount.objects.for_user(request.user), pk=account_id
    )
    if request.method == "POST":
        account.display_name = request.POST.get("display_name", "").strip()
        account.save(update_fields=["display_name"])
        messages.success(request, f'Renamed to "{account.effective_name}".')
        return HttpResponseRedirect(reverse("settings"))
    return render(request, "banking/rename_form.html", {
        "subject": "investment account",
        "object": account,
        "cancel_url": reverse("settings"),
        "current_value": account.display_name,
        "fallback_value": account.name,
    })


@login_required
@require_http_methods(["GET", "POST"])
def delete_holding(request, holding_id):
    holding = get_object_or_404(Holding.objects.for_user(request.user), pk=holding_id)
    account_id = holding.investment_account_id
    if request.method == "POST":
        symbol = holding.symbol
        holding.delete()
        messages.success(request, f"Deleted {symbol}.")
        return HttpResponseRedirect(reverse("investments:account_detail", args=[account_id]))
    return render(request, "investments/holding_confirm_delete.html", {"holding": holding})
