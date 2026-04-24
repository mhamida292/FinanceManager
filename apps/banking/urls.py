from django.urls import path

from . import views

app_name = "banking"

urlpatterns = [
    path("", views.banks_list, name="list"),
    path("link/", views.link_form, name="link"),
    path("<int:institution_id>/sync/", views.sync_institution_view, name="sync"),
    path("accounts/<int:account_id>/", views.account_detail, name="account_detail"),
]
