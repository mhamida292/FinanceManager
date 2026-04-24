from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.views.generic import TemplateView

from apps.assets.models import Asset
from apps.banking.models import Institution
from apps.investments.models import InvestmentAccount


class SettingsView(LoginRequiredMixin, TemplateView):
    template_name = "accounts/settings.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        ctx["institutions"] = Institution.objects.for_user(user).order_by("-last_synced_at")
        ctx["investment_accounts"] = (
            InvestmentAccount.objects.for_user(user)
            .filter(source="simplefin")
            .order_by("-last_synced_at")
        )
        ctx["scraped_assets"] = (
            Asset.objects.for_user(user)
            .filter(kind="scraped")
            .order_by("-last_priced_at")
        )
        return ctx


def healthz(request):
    return HttpResponse("ok", content_type="text/plain")
