import logging
import re
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.mail import send_mail
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.db import connection
from django.db import transaction
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django.views.decorators.http import require_POST
from django.utils.http import url_has_allowed_host_and_scheme
from kombu.exceptions import OperationalError

from core.forms import (
    CampaignForm,
    ContentTemplateForm,
    DatasetUploadForm,
    GeneratedPageForm,
    GoogleSheetForm,
    LeadCaptureForm,
    SignUpForm,
    WorkspaceCreateForm,
    WorkspaceDeleteForm,
    WorkspaceInvitationForm,
    WorkspaceMemberRoleForm,
    WorkspaceOwnershipTransferForm,
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
    WorkspaceInvitation,
    WorkspaceMember,
)
from core.tasks import process_dataset
from core.workspaces import (
    accessible_workspaces,
    can_manage_workspace,
    current_workspace,
)

logger = logging.getLogger(__name__)


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
        next_url = request.POST.get("next") or request.GET.get("next")
        if next_url and url_has_allowed_host_and_scheme(
            next_url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            return redirect(next_url)
        return redirect("dashboard")

    return render(
        request,
        "core/signup.html",
        {"form": form, "next": request.GET.get("next", "")},
    )


@login_required
@require_POST
def workspace_switch(request):
    workspace = get_object_or_404(
        accessible_workspaces(request.user),
        pk=request.POST.get("workspace_id"),
    )
    request.session["workspace_id"] = workspace.pk
    messages.success(request, f"Switched to {workspace.name}.")
    return redirect("dashboard")


@login_required
def workspace_settings(request):
    workspace = current_workspace(request)
    manager = can_manage_workspace(request.user, workspace)
    create_form = WorkspaceCreateForm(
        request.POST if request.POST.get("action") == "create" else None
    )
    invitation_form = WorkspaceInvitationForm(
        request.POST if request.POST.get("action") == "invite" else None,
        workspace=workspace,
        can_assign_admin=workspace.owner_id == request.user.pk,
    )
    transfer_form = WorkspaceOwnershipTransferForm(
        request.POST if request.POST.get("action") == "transfer" else None,
        workspace=workspace,
    )
    delete_form = WorkspaceDeleteForm(
        request.POST if request.POST.get("action") == "delete" else None,
        workspace=workspace,
    )

    if request.method == "POST" and request.POST.get("action") == "create":
        if create_form.is_valid():
            new_workspace = Workspace.objects.create(
                owner=request.user,
                name=create_form.cleaned_data["name"],
            )
            WorkspaceMember.objects.create(
                workspace=new_workspace,
                user=request.user,
                role=WorkspaceMember.Role.OWNER,
            )
            request.session["workspace_id"] = new_workspace.pk
            messages.success(request, f"{new_workspace.name} was created.")
            return redirect("workspace_settings")

    if request.method == "POST" and request.POST.get("action") == "invite":
        if not manager:
            messages.error(request, "Only workspace owners and admins can invite members.")
            return redirect("workspace_settings")
        if invitation_form.is_valid():
            invitation = invitation_form.save(commit=False)
            invitation.workspace = workspace
            invitation.invited_by = request.user
            invitation.expires_at = timezone.now() + timedelta(days=7)
            invitation.status = WorkspaceInvitation.Status.PENDING
            invitation.save()
            invite_url = request.build_absolute_uri(
                reverse(
                    "workspace_invitation_accept",
                    args=(invitation.token,),
                )
            )
            try:
                sent = send_mail(
                    subject=f"Invitation to join {workspace.name} on RankScale",
                    message=(
                        f"{request.user.get_username()} invited you to join "
                        f"{workspace.name} on RankScale as a "
                        f"{invitation.get_role_display().lower()}.\n\n"
                        f"Accept the invitation: {invite_url}\n\n"
                        "This link expires in 7 days. Sign in or create a RankScale "
                        "account using this invited email address to accept."
                    ),
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[invitation.email],
                    fail_silently=False,
                )
                if sent != 1:
                    raise RuntimeError("The configured email backend did not send the invitation.")
            except Exception:
                logger.exception(
                    "Failed to send workspace invitation for workspace %s",
                    workspace.pk,
                )
                invitation.status = WorkspaceInvitation.Status.REVOKED
                invitation.save(update_fields=("status",))
                messages.error(
                    request,
                    "The invitation could not be emailed. Check email configuration and try again.",
                )
                return redirect("workspace_settings")
            WorkspaceInvitation.objects.filter(
                workspace=workspace,
                email__iexact=invitation.email,
                status=WorkspaceInvitation.Status.PENDING,
            ).exclude(pk=invitation.pk).update(
                status=WorkspaceInvitation.Status.REVOKED
            )
            messages.success(request, f"Invitation sent to {invitation.email}.")
            return redirect("workspace_settings")

    if request.method == "POST" and request.POST.get("action") == "edit_member":
        membership = get_object_or_404(
            WorkspaceMember.objects.select_related("user"),
            pk=request.POST.get("member_id"),
            workspace=workspace,
        )
        if not manager:
            messages.error(request, "Only workspace owners and admins can edit roles.")
            return redirect("workspace_settings")
        if (
            membership.role == WorkspaceMember.Role.ADMIN
            and workspace.owner_id != request.user.pk
        ):
            messages.error(request, "Only the workspace owner can edit an admin's role.")
            return redirect("workspace_settings")
        if membership.role == WorkspaceMember.Role.OWNER:
            messages.error(request, "Transfer ownership before changing the owner's role.")
            return redirect("workspace_settings")
        if membership.user_id == request.user.pk:
            messages.error(request, "You cannot change your own workspace role.")
            return redirect("workspace_settings")
        role_form = WorkspaceMemberRoleForm(
            request.POST,
            initial={"role": membership.role},
            can_assign_admin=workspace.owner_id == request.user.pk,
        )
        if role_form.is_valid():
            membership.role = role_form.cleaned_data["role"]
            membership.save(update_fields=("role",))
            messages.success(
                request,
                f"{membership.user.username}'s role is now {membership.get_role_display()}.",
            )
        else:
            messages.error(request, "Choose a valid role for this workspace member.")
        return redirect("workspace_settings")

    if request.method == "POST" and request.POST.get("action") == "transfer":
        if workspace.owner_id != request.user.pk:
            messages.error(request, "Only the workspace owner can transfer ownership.")
            return redirect("workspace_settings")
        if transfer_form.is_valid():
            new_owner_membership = transfer_form.cleaned_data["new_owner"]
            with transaction.atomic():
                workspace = Workspace.objects.select_for_update().get(pk=workspace.pk)
                if workspace.owner_id != request.user.pk:
                    messages.error(request, "Workspace ownership changed. Please reload and try again.")
                    return redirect("workspace_settings")
                old_owner_membership = WorkspaceMember.objects.select_for_update().filter(
                    workspace=workspace,
                    user=request.user,
                    role=WorkspaceMember.Role.OWNER,
                ).first()
                new_owner_membership = WorkspaceMember.objects.select_for_update().filter(
                    pk=new_owner_membership.pk,
                    workspace=workspace,
                ).exclude(role=WorkspaceMember.Role.OWNER).first()
                if old_owner_membership is None or new_owner_membership is None:
                    messages.error(request, "The selected member is no longer eligible for transfer.")
                    return redirect("workspace_settings")
                workspace.owner = new_owner_membership.user
                workspace.save(update_fields=("owner", "updated_at"))
                new_owner_membership.role = WorkspaceMember.Role.OWNER
                new_owner_membership.save(update_fields=("role",))
                old_owner_membership.role = WorkspaceMember.Role.ADMIN
                old_owner_membership.save(update_fields=("role",))
            messages.success(
                request,
                f"Workspace ownership was transferred to {new_owner_membership.user.username}.",
            )
            return redirect("workspace_settings")

    if request.method == "POST" and request.POST.get("action") == "delete":
        if workspace.owner_id != request.user.pk:
            messages.error(request, "Only the workspace owner can delete this workspace.")
            return redirect("workspace_settings")
        if delete_form.is_valid():
            with transaction.atomic():
                workspace = Workspace.objects.select_for_update().get(pk=workspace.pk)
                if workspace.owner_id != request.user.pk:
                    messages.error(request, "Workspace ownership changed. Only its current owner can delete it.")
                    return redirect("workspace_settings")
                workspace_name = workspace.name
                workspace.delete()
            request.session.pop("workspace_id", None)
            messages.success(request, f"{workspace_name} and its data were deleted.")
            return redirect("dashboard")

    members = workspace.members.select_related("user")
    member_rows = [
        {
            "membership": membership,
            "role_form": WorkspaceMemberRoleForm(
                initial={"role": membership.role},
                can_assign_admin=workspace.owner_id == request.user.pk,
            ),
        }
        for membership in members
    ]
    return render(
        request,
        "core/workspace_settings.html",
        {
            "workspace": workspace,
            "members": member_rows,
            "pending_invitations": (
                workspace.invitations.filter(
                    status=WorkspaceInvitation.Status.PENDING,
                    expires_at__gt=timezone.now(),
                )
                if manager
                else WorkspaceInvitation.objects.none()
            ),
            "manager": manager,
            "is_owner": workspace.owner_id == request.user.pk,
            "create_form": create_form,
            "invitation_form": invitation_form,
            "transfer_form": transfer_form,
            "delete_form": delete_form,
        },
    )


@login_required
@require_POST
def workspace_member_remove(request, member_id):
    workspace = current_workspace(request)
    membership = get_object_or_404(
        WorkspaceMember.objects.select_related("user"),
        pk=member_id,
        workspace=workspace,
    )
    if not can_manage_workspace(request.user, workspace):
        messages.error(request, "Only workspace owners and admins can remove members.")
    elif membership.role == WorkspaceMember.Role.OWNER:
        messages.error(request, "The workspace owner cannot be removed.")
    elif (
        membership.role == WorkspaceMember.Role.ADMIN
        and workspace.owner_id != request.user.pk
    ):
        messages.error(request, "Only the workspace owner can remove an admin.")
    else:
        username = membership.user.username
        membership.delete()
        messages.success(request, f"{username} was removed from {workspace.name}.")
    return redirect("workspace_settings")


@login_required
@require_POST
def workspace_invitation_revoke(request, invitation_id):
    workspace = current_workspace(request)
    invitation = get_object_or_404(
        WorkspaceInvitation,
        pk=invitation_id,
        workspace=workspace,
        status=WorkspaceInvitation.Status.PENDING,
    )
    if not can_manage_workspace(request.user, workspace):
        messages.error(request, "Only workspace owners and admins can revoke invitations.")
    else:
        invitation.status = WorkspaceInvitation.Status.REVOKED
        invitation.save(update_fields=("status",))
        messages.success(request, f"Invitation to {invitation.email} was revoked.")
    return redirect("workspace_settings")


@login_required
@require_http_methods(["GET", "POST"])
def workspace_invitation_accept(request, token):
    invitation = get_object_or_404(
        WorkspaceInvitation.objects.select_related("workspace"),
        token=token,
    )
    if invitation.status != WorkspaceInvitation.Status.PENDING:
        messages.error(request, "This invitation is no longer available.")
        return redirect("dashboard")
    if invitation.is_expired:
        invitation.status = WorkspaceInvitation.Status.REVOKED
        invitation.save(update_fields=("status",))
        messages.error(request, "This invitation has expired. Ask a workspace admin for a new one.")
        return redirect("dashboard")
    if not request.user.email or request.user.email.casefold() != invitation.email.casefold():
        return HttpResponseForbidden(
            "Sign in with the email address that received this workspace invitation."
        )
    if request.method == "GET":
        return render(
            request,
            "core/workspace_invitation_accept.html",
            {"invitation": invitation},
        )

    with transaction.atomic():
        invitation = WorkspaceInvitation.objects.select_for_update().get(pk=invitation.pk)
        if invitation.status != WorkspaceInvitation.Status.PENDING or invitation.is_expired:
            messages.error(request, "This invitation is no longer available.")
            return redirect("dashboard")
        membership, created = WorkspaceMember.objects.get_or_create(
            workspace=invitation.workspace,
            user=request.user,
            defaults={"role": invitation.role},
        )
        if not created:
            messages.info(request, "You are already a member of this workspace.")
        invitation.status = WorkspaceInvitation.Status.ACCEPTED
        invitation.accepted_at = timezone.now()
        invitation.save(update_fields=("status", "accepted_at"))
    request.session["workspace_id"] = invitation.workspace_id
    if created:
        messages.success(request, f"You joined {invitation.workspace.name}.")
    return redirect("dashboard")


def _render_generated_page_content(campaign, template, overrides=None):
    variables = {
        "campaign_name": campaign.name,
        "brand_name": campaign.name,
        "target_keyword": campaign.target_keyword,
        "website_url": campaign.website_url,
        "company_name": campaign.name,
    }
    if template is not None:
        for definition in template.variables:
            if isinstance(definition, dict) and definition.get("name"):
                variables.setdefault(
                    definition["name"],
                    definition.get("default", ""),
                )
            elif isinstance(definition, str):
                variables.setdefault(definition, "")
    if overrides:
        variables.update(overrides)
    rendered = template.content if template is not None else ""
    return re.sub(
        r"{{\s*([A-Za-z_][A-Za-z0-9_]*)\s*}}",
        lambda match: str(variables.get(match.group(1), match.group(0))),
        rendered,
    )


@login_required
def content_templates(request):
    workspace = current_workspace(request)
    templates = ContentTemplate.objects.filter(workspace=workspace)
    form = ContentTemplateForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        template = form.save(commit=False)
        template.workspace = workspace
        template.save()
        messages.success(request, f"{template.title} was added to your template library.")
        return redirect("content_templates")

    return render(
        request,
        "core/content_templates.html",
        {"templates": templates, "form": form, "workspace": workspace},
    )


@login_required
def content_template_edit(request, template_id):
    workspace = current_workspace(request)
    template = get_object_or_404(
        ContentTemplate,
        pk=template_id,
        workspace=workspace,
    )
    form = ContentTemplateForm(request.POST or None, instance=template)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"{template.title} and its variables were updated.")
        return redirect("content_templates")
    return render(
        request,
        "core/content_template_edit.html",
        {"form": form, "template": template, "workspace": workspace},
    )


@login_required
def generated_pages(request):
    workspace = current_workspace(request)
    pages = GeneratedPage.objects.filter(workspace=workspace).select_related("campaign", "template")
    form = GeneratedPageForm(
        request.POST or None,
        workspace=workspace,
        initial={"template": request.GET.get("template")},
    )

    if request.method == "POST" and form.is_valid():
        page = form.save(commit=False)
        page.workspace = workspace
        page.variable_values = form.variable_values
        if page.template:
            page.content = _render_generated_page_content(
                page.campaign,
                page.template,
                page.variable_values,
            )
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
    workspace = current_workspace(request)
    campaign_leads = LeadCapture.objects.filter(workspace=workspace).select_related("campaign")
    form = LeadCaptureForm(request.POST or None, workspace=workspace)

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
    workspace = current_workspace(request)
    campaigns = Campaign.objects.filter(workspace=workspace)
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

    user_campaigns = Campaign.objects.filter(workspace=workspace)
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
    workspace = current_workspace(request)
    form = CampaignForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        campaign = form.save(commit=False)
        campaign.owner = request.user
        campaign.workspace = workspace
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
    workspace = current_workspace(request)
    campaign = get_object_or_404(
        Campaign,
        pk=campaign_id,
        workspace=workspace,
    )
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
            "workspace": workspace,
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
    workspace = current_workspace(request)
    dataset = get_object_or_404(
        Dataset.objects.select_related("campaign"),
        pk=dataset_id,
        campaign_id=campaign_id,
        campaign__workspace=workspace,
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
