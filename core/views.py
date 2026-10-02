from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login
from django.contrib.auth.views import LoginView
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone

from core.forms import CampaignForm, SignUpForm
from core.models import Campaign


class RankScaleLoginView(LoginView):
    template_name = "core/login.html"
    redirect_authenticated_user = True


def signup(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    form = SignUpForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, "Your RankScale account is ready.")
        return redirect("dashboard")

    return render(request, "core/signup.html", {"form": form})


@login_required
def dashboard(request):
    campaigns = Campaign.objects.filter(owner=request.user)
    search_query = request.GET.get("q", "").strip()[:120]
    status_filter = request.GET.get("status", "")

    if search_query:
        campaigns = campaigns.filter(
            name__icontains=search_query
        ) | campaigns.filter(
            website_url__icontains=search_query
        ) | campaigns.filter(
            target_keyword__icontains=search_query
        )

    valid_statuses = {value for value, _label in Campaign.Status.choices}
    if status_filter not in valid_statuses:
        status_filter = ""
    if status_filter:
        campaigns = campaigns.filter(status=status_filter)

    user_campaigns = Campaign.objects.filter(owner=request.user)
    return render(
        request,
        "core/dashboard.html",
        {
            "campaigns": campaigns,
            "search_query": search_query,
            "status_filter": status_filter,
            "total_campaigns": user_campaigns.count(),
            "active_campaigns": user_campaigns.filter(
                status=Campaign.Status.ACTIVE
            ).count(),
            "draft_campaigns": user_campaigns.filter(
                status=Campaign.Status.DRAFT
            ).count(),
            "today": timezone.localdate(),
        },
    )


@login_required
def campaign_create(request):
    form = CampaignForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        campaign = form.save(commit=False)
        campaign.owner = request.user
        campaign.save()
        messages.success(request, f"{campaign.name} was added to your campaigns.")
        return redirect("dashboard")

    return render(request, "core/campaign_form.html", {"form": form})


def health_check(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        return JsonResponse(
            {"status": "error", "database": "unavailable"},
            status=503,
        )

    return JsonResponse({"status": "ok", "database": "ok"})
