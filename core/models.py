from django.conf import settings
from django.db import models


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
