from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_http_methods
from django.views.generic import TemplateView

from apps.assets.models import Asset
from apps.assets.services import refresh_scraped_assets
from apps.banking.models import Institution
from apps.banking.services import sync_institution
from apps.investments.models import InvestmentAccount
from apps.investments.services import refresh_manual_prices, sync_simplefin_investments


class SettingsView(LoginRequiredMixin, TemplateView):
    template_name = "accounts/settings.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        ctx["institutions"] = (
            Institution.objects.for_user(user)
            .prefetch_related("accounts", "investment_accounts")
            .order_by("-last_synced_at")
        )
        ctx["manual_investment_accounts"] = (
            InvestmentAccount.objects.for_user(user)
            .filter(source="manual")
            .order_by("name")
        )
        ctx["scraped_assets"] = (
            Asset.objects.for_user(user)
            .filter(kind="scraped")
            .order_by("-last_priced_at")
        )
        return ctx


def healthz(request):
    return HttpResponse("ok", content_type="text/plain")


@require_http_methods(["GET", "POST"])
def signup(request):
    """Open signup. Access is gated at the network layer (Tailscale-only)."""
    if request.method == "POST":
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return HttpResponseRedirect(reverse("home"))
    else:
        form = UserCreationForm()
    return render(request, "accounts/signup.html", {"form": form})


@login_required
@require_http_methods(["POST"])
def sync_all(request):
    """One-shot: SimpleFIN bank + investment sync for every institution, then refresh manual investment prices and scraped asset prices."""
    user = request.user
    bank_txns = 0
    inv_holdings = 0
    errors: list[str] = []

    for inst in Institution.objects.for_user(user):
        try:
            r = sync_institution(inst)
            bank_txns += r.transactions_created
        except Exception as exc:
            errors.append(f"{inst.effective_name} bank sync: {exc}")
        try:
            r = sync_simplefin_investments(inst)
            inv_holdings += r.holdings_created
        except Exception as exc:
            errors.append(f"{inst.effective_name} investment sync: {exc}")

    try:
        refreshed_holdings = refresh_manual_prices(user=user)
    except Exception as exc:
        refreshed_holdings = 0
        errors.append(f"manual price refresh: {exc}")

    try:
        asset_result = refresh_scraped_assets(user=user)
        refreshed_assets = asset_result.updated
    except Exception as exc:
        refreshed_assets = 0
        errors.append(f"scraped asset refresh: {exc}")

    summary = (
        f"Synced: {bank_txns} new transaction(s), {inv_holdings} new holding(s), "
        f"{refreshed_holdings} manual price(s), {refreshed_assets} asset(s)."
    )
    if errors:
        messages.warning(request, summary + " Errors: " + "; ".join(errors))
    else:
        messages.success(request, summary)

    # Redirect back to where the user was, falling back to dashboard.
    next_url = request.POST.get("next") or reverse("home")
    if not next_url.startswith("/"):  # absolute or scheme-relative URLs not allowed
        next_url = reverse("home")
    return HttpResponseRedirect(next_url)
