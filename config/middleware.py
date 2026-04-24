from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse


class LoginRequiredMiddleware:
    """Redirect unauthenticated users to LOGIN_URL for all paths
    except whitelisted ones (login, logout, admin login, static).
    """

    EXEMPT_PATH_PREFIXES = (
        "/login/",
        "/logout/",
        "/admin/login/",
        "/static/",
        "/healthz",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            return self.get_response(request)
        if any(request.path.startswith(p) for p in self.EXEMPT_PATH_PREFIXES):
            return self.get_response(request)
        if request.path.startswith("/admin/"):
            # Django admin handles its own login redirect.
            return self.get_response(request)
        return redirect(f"{reverse('login')}?next={request.path}")
