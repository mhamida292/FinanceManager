from django.urls import path

from . import views

app_name = "investments"

urlpatterns = [
    path("", views.investments_list, name="list"),
    path("accounts/add/", views.add_manual_account, name="add_account"),
    path("accounts/<int:account_id>/edit/", views.edit_account, name="edit_account"),
    path("accounts/<int:account_id>/rename/", views.rename_investment_account, name="rename_account"),
    path("accounts/<int:account_id>/", views.account_detail, name="account_detail"),
    path("accounts/<int:account_id>/holdings/add/", views.add_holding, name="add_holding"),
    path("holdings/<int:holding_id>/edit/", views.edit_holding, name="edit_holding"),
    path("holdings/<int:holding_id>/delete/", views.delete_holding, name="delete_holding"),
    path("refresh/", views.refresh_prices, name="refresh_prices"),
    path("banks/<int:institution_id>/sync/", views.sync_investments_view, name="sync_from_bank"),
    path("accounts/<int:account_id>/delete/", views.delete_account, name="delete_account"),
]
