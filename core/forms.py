import re
from urllib.parse import parse_qs, urlparse

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.core.validators import FileExtensionValidator

from core.models import Campaign, ContentTemplate, GeneratedPage, LeadCapture, Workspace

MAX_DATASET_UPLOAD_SIZE = 10 * 1024 * 1024


class SignUpForm(UserCreationForm):
    email = forms.EmailField(required=True)
    first_name = forms.CharField(max_length=150, required=False)
    last_name = forms.CharField(max_length=150, required=False)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "first_name", "last_name", "email")


class CampaignForm(forms.ModelForm):
    website_url = forms.URLField(
        assume_scheme="https",
        widget=forms.URLInput(attrs={"placeholder": "https://example.com"}),
    )

    class Meta:
        model = Campaign
        fields = ("name", "website_url", "target_keyword", "status")
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "e.g. Spring product launch"}),
            "target_keyword": forms.TextInput(attrs={"placeholder": "e.g. sustainable skincare"}),
        }


class ContentTemplateForm(forms.ModelForm):
    variables = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "keyword, company_name, CTA"}),
        help_text="Comma-separated variable names used in the template body.",
    )

    class Meta:
        model = ContentTemplate
        fields = ("title", "slug", "category", "description", "content", "variables")
        widgets = {
            "slug": forms.TextInput(attrs={"placeholder": "spring-launch"}),
            "content": forms.Textarea(attrs={"rows": 12, "placeholder": "Write a reusable page or offer template..."}),
            "description": forms.Textarea(attrs={"rows": 3}),
        }

    def clean_variables(self):
        variables = self.cleaned_data.get("variables", "")
        if not variables:
            return []
        return [item.strip() for item in variables.split(",") if item.strip()]


class GeneratedPageForm(forms.ModelForm):
    campaign = forms.ModelChoiceField(queryset=Campaign.objects.none())

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        if user is None:
            return
        workspace = Workspace.ensure_for_user(user)
        self.fields["campaign"].queryset = Campaign.objects.filter(owner=user)
        self.fields["template"].queryset = ContentTemplate.objects.filter(workspace=workspace)

    class Meta:
        model = GeneratedPage
        fields = ("campaign", "title", "slug", "template", "status")
        widgets = {
            "title": forms.TextInput(attrs={"placeholder": "Spring landing page"}),
            "slug": forms.TextInput(attrs={"placeholder": "spring-launch"}),
            "template": forms.Select(),
        }


class LeadCaptureForm(forms.ModelForm):
    campaign = forms.ModelChoiceField(queryset=Campaign.objects.none())

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields["campaign"].queryset = Campaign.objects.filter(owner=user)

    class Meta:
        model = LeadCapture
        fields = ("campaign", "full_name", "email", "company", "source", "notes")
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 4, "placeholder": "Add context about interest, timeline, or conversion notes."}),
        }


class DatasetUploadForm(forms.Form):
    file = forms.FileField(
        label="Data file",
        validators=[FileExtensionValidator(allowed_extensions=("csv", "xlsx", "json", "pdf"))],
        widget=forms.ClearableFileInput(
            attrs={"accept": ".csv,.xlsx,.json,.pdf,text/csv,application/json,application/pdf"}
        ),
    )

    def clean_file(self):
        uploaded_file = self.cleaned_data["file"]
        if uploaded_file.size > MAX_DATASET_UPLOAD_SIZE:
            raise forms.ValidationError("Choose a file smaller than 10 MB.")
        return uploaded_file


class GoogleSheetForm(forms.Form):
    url = forms.URLField(
        label="Google Sheets link",
        widget=forms.URLInput(
            attrs={
                "placeholder": "https://docs.google.com/spreadsheets/d/.../edit",
                "autocomplete": "url",
                "spellcheck": "false",
            }
        ),
    )

    def clean_url(self):
        parsed = urlparse(self.cleaned_data["url"])
        match = re.match(r"^/spreadsheets/d/([A-Za-z0-9_-]+)(?:/|$)", parsed.path)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "docs.google.com"
            or not match
        ):
            raise forms.ValidationError(
                "Enter a Google Sheets share link from docs.google.com."
            )

        query = parse_qs(parsed.query)
        fragment = parse_qs(parsed.fragment.lstrip("#"))
        gid_values = query.get("gid") or fragment.get("gid")
        gid = gid_values[0] if gid_values else None
        if gid is not None and not gid.isdigit():
            raise forms.ValidationError("The sheet tab ID in this link is invalid.")

        sheet_id = match.group(1)
        canonical_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"
        return f"{canonical_url}?gid={gid}" if gid is not None else canonical_url
