from django.contrib import admin

from .models import Holding, InvestmentAccount, PortfolioSnapshot


@admin.register(InvestmentAccount)
class InvestmentAccountAdmin(admin.ModelAdmin):
    list_display = ("__str__", "source", "broker", "user", "last_synced_at")
    list_filter = ("source", "user")
    search_fields = ("name", "display_name", "broker", "external_id", "user__username")
    readonly_fields = ("created_at", "last_synced_at")


@admin.register(Holding)
class HoldingAdmin(admin.ModelAdmin):
    list_display = ("symbol", "investment_account", "shares", "current_price", "market_value", "cost_basis", "cost_basis_source")
    list_filter = ("cost_basis_source", "investment_account__source", "investment_account__user")
    search_fields = ("symbol", "description", "external_id")
    readonly_fields = ("last_priced_at", "market_value")


@admin.register(PortfolioSnapshot)
class PortfolioSnapshotAdmin(admin.ModelAdmin):
    list_display = ("date", "investment_account", "total_value")
    list_filter = ("investment_account__user", "date")
    date_hierarchy = "date"
