from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.db import connection
from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.urls import reverse
from django.views.decorators.http import require_POST
from kombu.exceptions import OperationalError

from core.forms import (
    CampaignForm,
    ContentTemplateForm,
    DatasetUploadForm,
    GeneratedPageForm,
    GoogleSheetForm,
    LeadCaptureForm,
    SignUpForm,
)
from core.google_sheets import (
    GoogleSheetsError,
    create_oauth_flow,
    encrypt_refresh_token,
    oauth_is_configured,
)
from core.models import (
    Campaign,
    ContentTemplate,
    Dataset,
    GeneratedPage,
    GoogleSheetsConnection,
    LeadCapture,
    Workspace,
)
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
        Workspace.ensure_for_user(user)
        login(request, user)
        messages.success(request, "Your RankScale account is ready.")
        return redirect("dashboard")

    return render(request, "core/signup.html", {"form": form})


def _render_generated_page_content(campaign, template, overrides=None):
    variables = {
        "campaign_name": campaign.name,
        "brand_name": campaign.name,
        "target_keyword": campaign.target_keyword,
        "website_url": campaign.website_url,
        "company_name": campaign.name,
    }
    if template is not None:
        for name in template.variables:
            variables.setdefault(name, "")
    if overrides:
        variables.update(overrides)
    rendered = template.content if template is not None else ""
    for key, value in variables.items():
        placeholder = "{{ " + key + " }}"
        rendered = rendered.replace(placeholder, str(value))
    return rendered


@login_required
def content_templates(request):
    workspace = Workspace.ensure_for_user(request.user)
    templates = ContentTemplate.objects.filter(workspace=workspace)
    form = ContentTemplateForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        template = form.save(commit=False)
        template.workspace = workspace
        template.slug = template.slug or "template"
        template.save()
        messages.success(request, f"{template.title} was added to your template library.")
        return redirect("content_templates")

    return render(
        request,
        "core/content_templates.html",
        {"templates": templates, "form": form, "workspace": workspace},
    )


@login_required
def generated_pages(request):
    workspace = Workspace.ensure_for_user(request.user)
    pages = GeneratedPage.objects.filter(workspace=workspace).select_related("campaign", "template")
    form = GeneratedPageForm(request.POST or None, user=request.user)

    if request.method == "POST" and form.is_valid():
        page = form.save(commit=False)
        page.workspace = workspace
        if page.template:
            page.content = _render_generated_page_content(page.campaign, page.template)
        else:
            page.content = page.title
        page.save()
        messages.success(request, f"{page.title} was generated successfully.")
        return redirect("generated_pages")

    return render(
        request,
        "core/generated_pages.html",
        {"pages": pages, "form": form, "workspace": workspace},
    )


@login_required
def leads(request):
    workspace = Workspace.ensure_for_user(request.user)
    campaign_leads = LeadCapture.objects.filter(workspace=workspace).select_related("campaign")
    form = LeadCaptureForm(request.POST or None, user=request.user)

    if request.method == "POST" and form.is_valid():
        lead = form.save(commit=False)
        lead.workspace = workspace
        lead.save()
        messages.success(request, f"{lead.full_name} was added to your lead list.")
        return redirect("leads")

    return render(
        request,
        "core/leads.html",
        {"leads": campaign_leads, "form": form, "workspace": workspace},
    )


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
    upload_form = DatasetUploadForm(
        request.POST if request.POST.get("source") == "file" else None,
        request.FILES if request.POST.get("source") == "file" else None,
    )
    sheet_form = GoogleSheetForm(
        request.POST if request.POST.get("source") == "google_sheet" else None
    )

    if request.method == "POST" and request.POST.get("source") == "file":
        if upload_form.is_valid():
            uploaded_file = upload_form.cleaned_data["file"]
            source_format = {
                ".csv": Dataset.SourceFormat.CSV,
                ".xlsx": Dataset.SourceFormat.XLSX,
                ".json": Dataset.SourceFormat.JSON,
                ".pdf": Dataset.SourceFormat.PDF,
            }[Path(uploaded_file.name).suffix.lower()]
            dataset = Dataset.objects.create(
                campaign=campaign,
                original_filename=uploaded_file.name[:255],
                source_format=source_format,
                file=uploaded_file,
            )
            if _queue_dataset(dataset):
                messages.success(request, f"{dataset.original_filename} was queued for import.")
            else:
                messages.error(request, dataset.error_message)
            return redirect("campaign_datasets", campaign_id=campaign.pk)

    if request.method == "POST" and request.POST.get("source") == "google_sheet":
        if sheet_form.is_valid():
            source_url = sheet_form.cleaned_data["url"]
            sheet_id = source_url.split("/d/", 1)[1].split("/", 1)[0]
            dataset = Dataset.objects.create(
                campaign=campaign,
                original_filename=f"Google Sheet {sheet_id}",
                source_format=Dataset.SourceFormat.GOOGLE_SHEET,
                source_url=source_url,
            )
            if _queue_dataset(dataset):
                messages.success(request, "The Google Sheet was queued for import.")
            else:
                messages.error(request, dataset.error_message)
            return redirect("campaign_datasets", campaign_id=campaign.pk)

    datasets = campaign.datasets.all()
    return render(
        request,
        "core/datasets.html",
        {
            "campaign": campaign,
            "upload_form": upload_form,
            "sheet_form": sheet_form,
            "datasets": datasets,
            "google_connected": GoogleSheetsConnection.objects.filter(
                user=request.user
            ).exists(),
            "google_oauth_configured": oauth_is_configured(),
            "has_running_import": datasets.filter(
                status__in=(Dataset.Status.QUEUED, Dataset.Status.PROCESSING)
            ).exists(),
        },
    )


@login_required
def google_oauth_authorize(request):
    redirect_uri = settings.GOOGLE_OAUTH_REDIRECT_URI or request.build_absolute_uri(
        reverse("google_oauth_callback")
    )
    try:
        flow = create_oauth_flow(redirect_uri)
    except GoogleSheetsError as exc:
        messages.error(request, str(exc))
        return redirect("dashboard")

    authorization_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    request.session["google_sheets_oauth_state"] = state
    return redirect(authorization_url)


@login_required
def google_oauth_callback(request):
    if request.GET.get("error"):
        messages.error(request, "Google Sheets connection was cancelled.")
        return redirect("dashboard")

    expected_state = request.session.pop("google_sheets_oauth_state", None)
    if not expected_state or request.GET.get("state") != expected_state:
        messages.error(request, "Google sign-in expired. Please try connecting again.")
        return redirect("dashboard")

    redirect_uri = settings.GOOGLE_OAUTH_REDIRECT_URI or request.build_absolute_uri(
        reverse("google_oauth_callback")
    ).split("?", 1)[0]
    try:
        flow = create_oauth_flow(redirect_uri, state=expected_state)
        flow.fetch_token(authorization_response=request.build_absolute_uri())
        refresh_token = flow.credentials.refresh_token
        if not refresh_token:
            existing = GoogleSheetsConnection.objects.filter(user=request.user).first()
            if existing:
                from core.google_sheets import decrypt_refresh_token

                refresh_token = decrypt_refresh_token(existing.encrypted_refresh_token)
            else:
                raise GoogleSheetsError(
                    "Google did not return a refresh token. Reconnect and approve offline access."
                )
        GoogleSheetsConnection.objects.update_or_create(
            user=request.user,
            defaults={
                "encrypted_refresh_token": encrypt_refresh_token(refresh_token),
                "scopes": " ".join(flow.credentials.scopes or settings.GOOGLE_SHEETS_SCOPES),
            },
        )
    except Exception:
        messages.error(
            request,
            "Google sign-in could not be completed. Check the OAuth client settings and try again.",
        )
        return redirect("dashboard")

    messages.success(request, "Google Sheets is connected with read-only access.")
    return redirect("dashboard")


@login_required
@require_POST
def google_oauth_disconnect(request):
    GoogleSheetsConnection.objects.filter(user=request.user).delete()
    messages.success(request, "Your Google Sheets connection was removed.")
    return redirect("dashboard")


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
