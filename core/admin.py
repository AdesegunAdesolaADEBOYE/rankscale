from django.contrib import admin

from core.models import (
    Campaign,
    ContentTemplate,
    Dataset,
    GeneratedPage,
    LeadCapture,
    Workspace,
    WorkspaceInvitation,
    WorkspaceMember,
)


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "status", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("name", "website_url", "target_keyword", "owner__username")


@admin.register(Dataset)
class DatasetAdmin(admin.ModelAdmin):
    list_display = ("original_filename", "source_format", "campaign", "status", "row_count", "created_at")
    list_filter = ("source_format", "status", "created_at")
    search_fields = ("original_filename", "campaign__name", "campaign__owner__username")
    readonly_fields = ("columns", "row_count", "error_message", "created_at", "updated_at")


@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "slug", "created_at")
    search_fields = ("name", "owner__username", "slug")
    readonly_fields = ("slug", "created_at", "updated_at")


@admin.register(WorkspaceMember)
class WorkspaceMemberAdmin(admin.ModelAdmin):
    list_display = ("workspace", "user", "role", "joined_at")
    list_filter = ("role", "joined_at")
    search_fields = ("workspace__name", "user__username", "user__email")


@admin.register(WorkspaceInvitation)
class WorkspaceInvitationAdmin(admin.ModelAdmin):
    list_display = ("email", "workspace", "role", "status", "invited_by", "expires_at")
    list_filter = ("status", "role", "created_at")
    search_fields = ("email", "workspace__name", "invited_by__username")
    readonly_fields = ("token", "created_at", "accepted_at")


@admin.register(ContentTemplate)
class ContentTemplateAdmin(admin.ModelAdmin):
    list_display = ("title", "workspace", "category", "updated_at")
    list_filter = ("category", "updated_at")
    search_fields = ("title", "workspace__name", "slug")


@admin.register(GeneratedPage)
class GeneratedPageAdmin(admin.ModelAdmin):
    list_display = ("title", "workspace", "campaign", "status", "updated_at")
    list_filter = ("status", "updated_at")
    search_fields = ("title", "workspace__name", "campaign__name", "slug")


@admin.register(LeadCapture)
class LeadCaptureAdmin(admin.ModelAdmin):
    list_display = ("full_name", "email", "workspace", "campaign", "source", "created_at")
    list_filter = ("source", "created_at")
    search_fields = ("full_name", "email", "company", "workspace__name", "campaign__name")
