from django.urls import path

from . import views

app_name = "banking"

urlpatterns = [
    path("", views.banks_list, name="list"),
    path("link/", views.link_form, name="link"),
    path("<int:institution_id>/sync/", views.sync_institution_view, name="sync"),
    path("<int:institution_id>/rename/", views.rename_institution, name="rename_institution"),
    path("accounts/<int:account_id>/", views.account_detail, name="account_detail"),
    path("accounts/<int:account_id>/rename/", views.rename_account, name="rename_account"),
    path("transactions/<int:transaction_id>/rename/", views.rename_transaction, name="rename_transaction"),
    path("<int:institution_id>/delete/", views.delete_institution, name="delete_institution"),
    path("accounts/<int:account_id>/delete/", views.delete_account, name="delete_account"),
]
