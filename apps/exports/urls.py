from django.urls import path

from . import views

app_name = "exports"
urlpatterns = [
    path("xlsx/", views.xlsx_export, name="xlsx"),
]
