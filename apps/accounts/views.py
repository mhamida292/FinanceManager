from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.shortcuts import redirect
from django.views.generic import TemplateView


class SettingsView(LoginRequiredMixin, TemplateView):
    template_name = "accounts/settings.html"


def home_redirect(request):
    # Real dashboard ships in Phase 5; for now, send authenticated users to settings.
    return redirect("settings")


def healthz(request):
    return HttpResponse("ok", content_type="text/plain")
