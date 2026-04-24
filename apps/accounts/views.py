from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.views.generic import TemplateView


class SettingsView(LoginRequiredMixin, TemplateView):
    template_name = "accounts/settings.html"


def healthz(request):
    return HttpResponse("ok", content_type="text/plain")
