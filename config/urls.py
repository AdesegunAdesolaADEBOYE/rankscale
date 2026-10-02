from django.contrib import admin
from django.contrib.auth.views import LogoutView
from django.urls import path

from core.views import (
    RankScaleLoginView,
    campaign_create,
    dashboard,
    health_check,
    signup,
)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", dashboard, name="dashboard"),
    path("login/", RankScaleLoginView.as_view(), name="login"),
    path("signup/", signup, name="signup"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("campaigns/new/", campaign_create, name="campaign_create"),
    path("api/health/", health_check, name="health-check"),
]
