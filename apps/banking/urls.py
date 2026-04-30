from django.urls import path

from . import views

app_name = "banking"

urlpatterns = [
    path("", views.banks_list, name="list"),
    path("link/", views.link_form, name="link"),
    path("link/simplefin/", views.link_form_simplefin, name="link_simplefin"),
    path("link/teller/", views.link_form_teller, name="link_teller"),
    path("link/teller/callback/", views.link_form_teller_callback, name="link_teller_callback"),
    path("<int:institution_id>/sync/", views.sync_institution_view, name="sync"),
    path("<int:institution_id>/rename/", views.rename_institution, name="rename_institution"),
    path("accounts/<int:account_id>/", views.account_detail, name="account_detail"),
    path("accounts/<int:account_id>/rename/", views.rename_account, name="rename_account"),
    path("transactions/<int:transaction_id>/rename/", views.rename_transaction, name="rename_transaction"),
    path("transactions/bulk-set-category/", views.bulk_set_category, name="bulk_set_category"),
    path("transactions/bulk-set-category-by-filter/", views.bulk_set_category_by_filter, name="bulk_set_category_by_filter"),
    path("transactions/<int:transaction_id>/set-category/", views.set_category, name="set_category"),
    path("<int:institution_id>/delete/", views.delete_institution, name="delete_institution"),
    path("accounts/<int:account_id>/delete/", views.delete_account, name="delete_account"),
]
