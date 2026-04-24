from django.urls import path

from . import views

app_name = "assets"

urlpatterns = [
    path("", views.assets_list, name="list"),
    path("add/", views.add_asset, name="add"),
    path("<int:asset_id>/edit/", views.edit_asset, name="edit"),
    path("<int:asset_id>/delete/", views.delete_asset_view, name="delete"),
    path("refresh/", views.refresh_prices, name="refresh"),
]
