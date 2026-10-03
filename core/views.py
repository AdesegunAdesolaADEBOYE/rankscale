from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.db import connection
from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from kombu.exceptions import OperationalError

from core.forms import CampaignForm, DatasetUploadForm, SignUpForm
from core.models import Campaign, Dataset
from core.tasks import process_dataset


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


def _queue_dataset(dataset):
    try:
        process_dataset.apply_async(args=(dataset.pk,), retry=False)
    except OperationalError:
        dataset.status = Dataset.Status.FAILED
        dataset.error_message = (
            "Background processing is unavailable. Start Redis and the Celery worker, then retry."
        )
        dataset.save(update_fields=("status", "error_message", "updated_at"))
        return False
    return True


@login_required
def campaign_datasets(request, campaign_id):
    campaign = get_object_or_404(Campaign, pk=campaign_id, owner=request.user)
    form = DatasetUploadForm(request.POST or None, request.FILES or None)

    if request.method == "POST" and form.is_valid():
        uploaded_file = form.cleaned_data["file"]
        dataset = Dataset.objects.create(
            campaign=campaign,
            original_filename=uploaded_file.name[:255],
            file=uploaded_file,
        )
        if _queue_dataset(dataset):
            messages.success(request, f"{dataset.original_filename} was queued for import.")
        else:
            messages.error(request, dataset.error_message)
        return redirect("campaign_datasets", campaign_id=campaign.pk)

    datasets = campaign.datasets.all()
    return render(
        request,
        "core/datasets.html",
        {
            "campaign": campaign,
            "form": form,
            "datasets": datasets,
            "has_running_import": datasets.filter(
                status__in=(Dataset.Status.QUEUED, Dataset.Status.PROCESSING)
            ).exists(),
        },
    )


@login_required
@require_POST
def dataset_retry(request, campaign_id, dataset_id):
    dataset = get_object_or_404(
        Dataset.objects.select_related("campaign"),
        pk=dataset_id,
        campaign_id=campaign_id,
        campaign__owner=request.user,
    )
    if dataset.status != Dataset.Status.FAILED:
        messages.info(request, "Only failed imports can be retried.")
        return redirect("campaign_datasets", campaign_id=campaign_id)

    dataset.status = Dataset.Status.QUEUED
    dataset.error_message = ""
    dataset.row_count = 0
    dataset.columns = []
    dataset.save(update_fields=("status", "error_message", "row_count", "columns", "updated_at"))
    if _queue_dataset(dataset):
        messages.success(request, f"{dataset.original_filename} was queued again.")
    else:
        messages.error(request, dataset.error_message)
    return redirect("campaign_datasets", campaign_id=campaign_id)


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
