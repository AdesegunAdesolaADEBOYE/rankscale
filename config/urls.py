from django.contrib import admin
from django.contrib.auth.views import LogoutView
from django.urls import path

from core.views import (
    RankScaleLoginView,
    campaign_create,
    campaign_datasets,
    content_templates,
    content_template_edit,
    dashboard,
    dataset_retry,
    generated_pages,
    google_oauth_authorize,
    google_oauth_callback,
    google_oauth_disconnect,
    health_check,
    leads,
    signup,
    workspace_member_remove,
    workspace_invitation_accept,
    workspace_invitation_revoke,
    workspace_settings,
    workspace_switch,
)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", dashboard, name="dashboard"),
    path("login/", RankScaleLoginView.as_view(), name="login"),
    path("signup/", signup, name="signup"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("campaigns/new/", campaign_create, name="campaign_create"),
    path("campaigns/<int:campaign_id>/datasets/", campaign_datasets, name="campaign_datasets"),
    path(
        "campaigns/<int:campaign_id>/datasets/<int:dataset_id>/retry/",
        dataset_retry,
        name="dataset_retry",
    ),
    path("templates/", content_templates, name="content_templates"),
    path(
        "templates/<int:template_id>/edit/",
        content_template_edit,
        name="content_template_edit",
    ),
    path("generated-pages/", generated_pages, name="generated_pages"),
    path("leads/", leads, name="leads"),
    path("workspaces/", workspace_settings, name="workspace_settings"),
    path("workspaces/switch/", workspace_switch, name="workspace_switch"),
    path(
        "workspaces/members/<int:member_id>/remove/",
        workspace_member_remove,
        name="workspace_member_remove",
    ),
    path(
        "workspaces/invitations/<uuid:token>/accept/",
        workspace_invitation_accept,
        name="workspace_invitation_accept",
    ),
    path(
        "workspaces/invitations/<int:invitation_id>/revoke/",
        workspace_invitation_revoke,
        name="workspace_invitation_revoke",
    ),
    path("integrations/google/authorize/", google_oauth_authorize, name="google_oauth_authorize"),
    path("integrations/google/callback/", google_oauth_callback, name="google_oauth_callback"),
    path("integrations/google/disconnect/", google_oauth_disconnect, name="google_oauth_disconnect"),
    path("api/health/", health_check, name="health-check"),
]
