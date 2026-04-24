from django.contrib import admin

from .models import Liability


@admin.register(Liability)
class LiabilityAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "balance", "last_updated_at")
    list_filter = ("user",)
    search_fields = ("name", "notes")
    readonly_fields = ("created_at", "last_updated_at")
