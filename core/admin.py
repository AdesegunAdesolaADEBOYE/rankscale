from django.contrib import admin

from core.models import Campaign, Dataset


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "status", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("name", "website_url", "target_keyword", "owner__username")


@admin.register(Dataset)
class DatasetAdmin(admin.ModelAdmin):
    list_display = ("original_filename", "campaign", "status", "row_count", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("original_filename", "campaign__name", "campaign__owner__username")
    readonly_fields = ("columns", "row_count", "error_message", "created_at", "updated_at")
