from django.urls import path

from . import views

app_name = "liabilities"

urlpatterns = [
    path("", views.liabilities_list, name="list"),
    path("add/", views.add_liability, name="add"),
    path("<int:liability_id>/edit/", views.edit_liability, name="edit"),
    path("<int:liability_id>/delete/", views.delete_liability, name="delete"),
]
