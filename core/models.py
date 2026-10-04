import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.text import slugify


class Workspace(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="workspaces",
    )
    name = models.CharField(max_length=120, default="Personal workspace")
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name or self.owner.get_username())
            slug = base
            index = 2
            while Workspace.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base}-{index}"
                index += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    @staticmethod
    def ensure_for_user(user):
        workspace = (
            Workspace.objects.filter(members__user=user)
            .order_by("created_at")
            .first()
        )
        if workspace is None:
            workspace = Workspace.objects.create(
                owner=user,
                name=f"{user.get_full_name() or user.username}'s workspace",
            )
        WorkspaceMember.objects.get_or_create(
            workspace=workspace,
            user=workspace.owner,
            defaults={"role": WorkspaceMember.Role.OWNER},
        )
        WorkspaceMember.objects.get_or_create(
            workspace=workspace,
            user=user,
            defaults={
                "role": (
                    WorkspaceMember.Role.OWNER
                    if user.pk == workspace.owner_id
                    else WorkspaceMember.Role.MEMBER
                )
            },
        )
        return workspace


class WorkspaceMember(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        ADMIN = "admin", "Admin"
        MEMBER = "member", "Member"

    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="members",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="workspace_memberships",
    )
    role = models.CharField(max_length=12, choices=Role.choices, default=Role.MEMBER)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("joined_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("workspace", "user"),
                name="unique_workspace_member",
            )
        ]

    def __str__(self):
        return f"{self.user} — {self.workspace} ({self.role})"


class WorkspaceInvitation(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        REVOKED = "revoked", "Revoked"

    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="invitations",
    )
    email = models.EmailField()
    role = models.CharField(
        max_length=12,
        choices=(
            (WorkspaceMember.Role.ADMIN, "Admin"),
            (WorkspaceMember.Role.MEMBER, "Member"),
        ),
        default=WorkspaceMember.Role.MEMBER,
    )
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="workspace_invitations_sent",
    )
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.PENDING,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)

    @property
    def is_expired(self):
        return self.expires_at <= timezone.now()

    def __str__(self):
        return f"{self.email} invited to {self.workspace}"


class Campaign(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ACTIVE = "active", "Active"
        PAUSED = "paused", "Paused"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="campaigns",
    )
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="campaigns",
    )
    name = models.CharField(max_length=120)
    website_url = models.URLField(max_length=300)
    target_keyword = models.CharField(max_length=160)
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at",)

    def save(self, *args, **kwargs):
        if self.workspace_id is None and self.owner_id:
            self.workspace = Workspace.ensure_for_user(self.owner)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Dataset(models.Model):
    class SourceFormat(models.TextChoices):
        CSV = "csv", "CSV"
        XLSX = "xlsx", "Excel workbook"
        JSON = "json", "JSON"
        PDF = "pdf", "PDF"
        GOOGLE_SHEET = "google_sheet", "Google Sheets"

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        PROCESSING = "processing", "Processing"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"

    campaign = models.ForeignKey(
        Campaign,
        on_delete=models.CASCADE,
        related_name="datasets",
    )
    original_filename = models.CharField(max_length=255)
    source_format = models.CharField(
        max_length=16,
        choices=SourceFormat.choices,
        default=SourceFormat.CSV,
    )
    source_url = models.URLField(max_length=500, blank=True)
    file = models.FileField(upload_to="datasets/%Y/%m/%d", blank=True)
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.QUEUED,
    )
    columns = models.JSONField(default=list, blank=True)
    row_count = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return self.original_filename


class DatasetRow(models.Model):
    dataset = models.ForeignKey(
        Dataset,
        on_delete=models.CASCADE,
        related_name="rows",
    )
    row_number = models.PositiveIntegerField()
    data = models.JSONField()

    class Meta:
        ordering = ("row_number",)
        constraints = [
            models.UniqueConstraint(
                fields=("dataset", "row_number"),
                name="unique_dataset_row_number",
            )
        ]


class ContentTemplate(models.Model):
    class Category(models.TextChoices):
        LANDING_PAGE = "landing_page", "Landing page"
        BLOG_POST = "blog_post", "Blog post"
        LEAD_MAGNET = "lead_magnet", "Lead magnet"
        OFFER = "offer", "Offer"

    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="content_templates",
    )
    title = models.CharField(max_length=160)
    slug = models.SlugField(max_length=160, unique=True)
    category = models.CharField(
        max_length=24,
        choices=Category.choices,
        default=Category.LANDING_PAGE,
    )
    description = models.TextField(blank=True)
    content = models.TextField()
    variables = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at",)

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title)
            slug = base or "template"
            index = 2
            while ContentTemplate.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base}-{index}"
                index += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title


class GeneratedPage(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        ARCHIVED = "archived", "Archived"

    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="generated_pages",
    )
    campaign = models.ForeignKey(
        Campaign,
        on_delete=models.CASCADE,
        related_name="pages",
    )
    template = models.ForeignKey(
        ContentTemplate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="generated_pages",
    )
    title = models.CharField(max_length=160)
    slug = models.SlugField(max_length=160)
    content = models.TextField()
    variable_values = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("workspace", "slug"),
                name="unique_workspace_generated_page_slug",
            )
        ]

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title)
            slug = base or "page"
            index = 2
            while GeneratedPage.objects.filter(workspace=self.workspace, slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base}-{index}"
                index += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title


class LeadCapture(models.Model):
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="leads",
    )
    campaign = models.ForeignKey(
        Campaign,
        on_delete=models.CASCADE,
        related_name="leads",
    )
    full_name = models.CharField(max_length=140)
    email = models.EmailField()
    company = models.CharField(max_length=140, blank=True)
    source = models.CharField(max_length=80, default="website")
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return self.full_name


class GoogleSheetsConnection(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="google_sheets_connection",
    )
    encrypted_refresh_token = models.TextField()
    scopes = models.CharField(max_length=500, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Google Sheets connection for {self.user}"
