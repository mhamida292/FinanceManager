from django.contrib import admin

from .models import Asset, AssetPriceSnapshot


@admin.register(Asset)
class AssetAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "user", "quantity", "unit", "current_value", "last_priced_at")
    list_filter = ("kind", "user")
    search_fields = ("name", "notes", "source_url", "user__username")
    readonly_fields = ("created_at", "last_priced_at")


@admin.register(AssetPriceSnapshot)
class AssetPriceSnapshotAdmin(admin.ModelAdmin):
    list_display = ("at", "asset", "value")
    list_filter = ("asset__user",)
    date_hierarchy = "at"
