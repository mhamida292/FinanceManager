from django.contrib.auth import views as auth_views
from django.urls import path

from . import views
from apps.banking import views as banking_views
from apps.dashboard import views as dashboard_views

urlpatterns = [
    path("login/", auth_views.LoginView.as_view(template_name="accounts/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("settings/", views.SettingsView.as_view(), name="settings"),
    path("sync-all/", views.sync_all, name="sync_all"),
    path("transactions/", banking_views.transactions_list, name="transactions"),
    path("", dashboard_views.dashboard, name="home"),
    path("healthz", views.healthz, name="healthz"),
]
