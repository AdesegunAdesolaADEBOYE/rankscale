from django.contrib import admin
from django.contrib.auth.views import LogoutView
from django.urls import path

from core.views import (
    RankScaleLoginView,
    campaign_create,
    campaign_datasets,
    dashboard,
    dataset_retry,
    health_check,
    google_oauth_authorize,
    google_oauth_callback,
    google_oauth_disconnect,
    signup,
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
    path("integrations/google/authorize/", google_oauth_authorize, name="google_oauth_authorize"),
    path("integrations/google/callback/", google_oauth_callback, name="google_oauth_callback"),
    path("integrations/google/disconnect/", google_oauth_disconnect, name="google_oauth_disconnect"),
    path("api/health/", health_check, name="health-check"),
]
