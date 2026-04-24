from django.contrib import admin

from .models import Account, Institution, Transaction


@admin.register(Institution)
class InstitutionAdmin(admin.ModelAdmin):
    list_display = ("name", "display_name", "user", "provider", "last_synced_at", "created_at")
    list_filter = ("provider", "user")
    search_fields = ("name", "display_name", "user__username")
    readonly_fields = ("created_at", "last_synced_at")


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ("__str__", "display_name", "type", "balance", "currency", "last_synced_at")
    list_filter = ("type", "institution__user")
    search_fields = ("name", "display_name", "org_name", "external_id")
    readonly_fields = ("last_synced_at",)


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ("posted_at", "payee", "amount", "account", "pending")
    list_filter = ("pending", "account__institution__user")
    search_fields = ("payee", "description", "memo", "external_id")
    date_hierarchy = "posted_at"
