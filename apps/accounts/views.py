from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django.views.generic import TemplateView

from apps.assets.models import Asset
from apps.banking.models import Institution
from apps.investments.models import InvestmentAccount

from .models import SyncRun
from .services import _spawn_thread, format_absolute, format_relative, start_sync

# Indirection so tests can monkeypatch the runner without touching services.
_default_runner = _spawn_thread

# Stuck-run threshold: a "running" SyncRun older than this is coerced to "error" on read.
STALE_RUN_AFTER = timedelta(minutes=5)


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
    """Kick off a background refresh and redirect immediately.

    SimpleFIN sync is intentionally not wired here right now — only manual
    investment prices and scraped assets refresh on the ⟳ button. SimpleFIN
    services remain available for per-institution sync from the settings page
    and for future re-enable.
    """
    user = request.user

    if SyncRun.objects.filter(user=user, status=SyncRun.STATUS_RUNNING).exists():
        # Defense-in-depth: the UI button is disabled while running, but a stale
        # tab could still POST. Don't start a second worker.
        messages.info(request, "A sync is already in progress.")
    else:
        start_sync(user, runner=_default_runner)
        messages.success(request, "Sync started.")

    next_url = request.POST.get("next") or reverse("home")
    if not next_url.startswith("/"):
        next_url = reverse("home")
    return HttpResponseRedirect(next_url)


@login_required
@require_http_methods(["GET"])
def sync_status(request):
    """JSON: latest sync state for the current user. Polled by the top-bar JS."""
    run = SyncRun.objects.filter(user=request.user).order_by("-started_at").first()

    if run is None:
        return JsonResponse({
            "status": "idle",
            "summary": "",
            "errors": "",
            "finished_at_iso": None,
            "finished_at_absolute": None,
            "finished_at_relative": None,
        })

    if run.status == SyncRun.STATUS_RUNNING and timezone.now() - run.started_at > STALE_RUN_AFTER:
        SyncRun.objects.filter(pk=run.pk, status=SyncRun.STATUS_RUNNING).update(
            status=SyncRun.STATUS_ERROR,
            errors_text="sync interrupted",
            finished_at=timezone.now(),
        )
        run.refresh_from_db()

    return JsonResponse({
        "status": run.status,
        "summary": run.summary,
        "errors": run.errors_text,
        "finished_at_iso": run.finished_at.isoformat() if run.finished_at else None,
        "finished_at_absolute": format_absolute(run.finished_at) if run.finished_at else None,
        "finished_at_relative": format_relative(run.finished_at) if run.finished_at else None,
    })
