import re
from urllib.parse import parse_qs, urlparse

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import get_user_model
from django.core.validators import FileExtensionValidator
from django.core.exceptions import ValidationError
import re

from core.models import (
    Campaign,
    ContentTemplate,
    GeneratedPage,
    LeadCapture,
    Workspace,
    WorkspaceInvitation,
    WorkspaceMember,
)

User = get_user_model()
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


class WorkspaceCreateForm(forms.Form):
    name = forms.CharField(
        max_length=120,
        widget=forms.TextInput(attrs={"placeholder": "Acme SEO team"}),
    )


class WorkspaceInvitationForm(forms.ModelForm):
    class Meta:
        model = WorkspaceInvitation
        fields = ("email", "role")
        widgets = {
            "email": forms.EmailInput(attrs={"placeholder": "teammate@example.com"}),
        }

    def __init__(self, *args, **kwargs):
        self.workspace = kwargs.pop("workspace")
        can_assign_admin = kwargs.pop("can_assign_admin", False)
        super().__init__(*args, **kwargs)
        if not can_assign_admin:
            self.fields["role"].choices = (
                (WorkspaceMember.Role.MEMBER, "Member"),
            )

    def clean_email(self):
        email = self.cleaned_data["email"].strip().casefold()
        User = get_user_model()
        existing_user = User.objects.filter(email__iexact=email).first()
        if existing_user and WorkspaceMember.objects.filter(
            workspace=self.workspace,
            user=existing_user,
        ).exists():
            raise forms.ValidationError("That user is already a workspace member.")
        return email


class WorkspaceMemberRoleForm(forms.Form):
    role = forms.ChoiceField(
        choices=(
            (WorkspaceMember.Role.ADMIN, "Admin"),
            (WorkspaceMember.Role.MEMBER, "Member"),
        )
    )

    def __init__(self, *args, **kwargs):
        can_assign_admin = kwargs.pop("can_assign_admin", False)
        super().__init__(*args, **kwargs)
        if not can_assign_admin:
            self.fields["role"].choices = (
                (WorkspaceMember.Role.MEMBER, "Member"),
            )


class WorkspaceOwnershipTransferForm(forms.Form):
    new_owner = forms.ModelChoiceField(
        queryset=WorkspaceMember.objects.none(),
        label="New owner",
    )

    def __init__(self, *args, **kwargs):
        workspace = kwargs.pop("workspace")
        super().__init__(*args, **kwargs)
        self.fields["new_owner"].queryset = WorkspaceMember.objects.filter(
            workspace=workspace,
        ).exclude(role=WorkspaceMember.Role.OWNER).select_related("user")
        self.fields["new_owner"].label_from_instance = (
            lambda membership: (
                f"{membership.user.get_username()} ({membership.get_role_display()})"
            )
        )

    def clean_new_owner(self):
        return self.cleaned_data["new_owner"]


class WorkspaceDeleteForm(forms.Form):
    confirmation = forms.CharField(
        label="Type the workspace name to confirm",
        widget=forms.TextInput(attrs={"autocomplete": "off"}),
    )

    def __init__(self, *args, **kwargs):
        self.workspace = kwargs.pop("workspace")
        super().__init__(*args, **kwargs)

    def clean_confirmation(self):
        confirmation = self.cleaned_data["confirmation"].strip()
        if confirmation != self.workspace.name:
            raise forms.ValidationError("Enter the workspace name exactly to confirm.")
        return confirmation


class ContentTemplateForm(forms.ModelForm):
    variables = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={
                "rows": 6,
                "placeholder": (
                    "brand_name | Brand name | Acme\n"
                    "offer | Special offer | Free consultation | required"
                ),
            }
        ),
        help_text=(
            "One variable per line: name | label | default value | required. "
            "Names in {{ double braces }} are detected automatically."
        ),
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
        raw_variables = self.cleaned_data.get("variables", "")
        content = self.cleaned_data.get("content", "")
        definitions = {}
        for line in raw_variables.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = [part.strip() for part in line.split("|")]
            names = [name.strip() for name in parts[0].split(",") if name.strip()]
            if len(names) > 1 and len(parts) == 1:
                continue
            elif len(names) != 1:
                raise ValidationError("Enter one variable name per line.")
            name = names[0]
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                raise ValidationError(
                    f"'{name}' is invalid. Use letters, numbers, and underscores; start with a letter or underscore."
                )
            if name in definitions:
                raise ValidationError(f"'{name}' is listed more than once.")
            if name in {"campaign_name", "brand_name", "company_name", "target_keyword", "website_url"}:
                continue
            if len(parts) > 4:
                raise ValidationError(
                    "Use name | label | default value | required on each line."
                )
            label = parts[1] if len(parts) > 1 and parts[1] else name.replace("_", " ").title()
            default = parts[2] if len(parts) > 2 else ""
            required = len(parts) > 3 and parts[3].casefold() in {
                "required",
                "yes",
                "true",
            }
            if len(parts) > 3 and parts[3].casefold() not in {
                "required",
                "yes",
                "true",
                "optional",
                "no",
                "false",
            }:
                raise ValidationError("Mark the final option as required or optional.")
            definitions[name] = {
                "name": name,
                "label": label,
                "default": default,
                "required": required,
            }

        placeholders = set(
            re.findall(r"{{\s*([A-Za-z_][A-Za-z0-9_]*)\s*}}", content)
        )
        for name in placeholders:
            if name not in definitions and name not in {
                "campaign_name",
                "brand_name",
                "company_name",
                "target_keyword",
                "website_url",
            }:
                definitions[name] = {
                    "name": name,
                    "label": name.replace("_", " ").title(),
                    "default": "",
                    "required": False,
                }
        return list(definitions.values())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and not self.is_bound:
            self.initial["variables"] = "\n".join(
                " | ".join(
                    (
                        item["name"],
                        item.get("label", item["name"].replace("_", " ").title()),
                        item.get("default", ""),
                        "required" if item.get("required") else "optional",
                    )
                )
                for item in self.instance.variables
                if isinstance(item, dict) and item.get("name")
            )


class GeneratedPageForm(forms.ModelForm):
    campaign = forms.ModelChoiceField(queryset=Campaign.objects.none())

    def __init__(self, *args, **kwargs):
        workspace = kwargs.pop("workspace", None)
        super().__init__(*args, **kwargs)
        if workspace is None:
            return
        self.fields["campaign"].queryset = Campaign.objects.filter(workspace=workspace)
        self.fields["template"].queryset = ContentTemplate.objects.filter(workspace=workspace)
        template_id = (
            self.data.get("template")
            if self.is_bound
            else self.initial.get("template")
        )
        template = self.fields["template"].queryset.filter(pk=template_id).first()
        if template is not None:
            for definition in template.variables:
                if not isinstance(definition, dict) or not definition.get("name"):
                    continue
                name = definition["name"]
                self.fields[f"variable_{name}"] = forms.CharField(
                    label=definition.get("label") or name.replace("_", " ").title(),
                    initial=definition.get("default", ""),
                    required=definition.get("required", False),
                )
        elif self.instance.pk:
            for name, value in self.instance.variable_values.items():
                self.fields[f"variable_{name}"] = forms.CharField(
                    label=name.replace("_", " ").title(),
                    initial=value,
                    required=False,
                )

    @property
    def variable_values(self):
        return {
            name.removeprefix("variable_"): self.cleaned_data[name]
            for name in self.fields
            if name.startswith("variable_") and name in self.cleaned_data
        }

    class Meta:
        model = GeneratedPage
        fields = ("campaign", "title", "slug", "template", "status")
        widgets = {
            "title": forms.TextInput(attrs={"placeholder": "Spring landing page"}),
            "slug": forms.TextInput(attrs={"placeholder": "spring-launch"}),
            "template": forms.Select(
                attrs={"onchange": "window.location.search='?template='+this.value"}
            ),
        }


class LeadCaptureForm(forms.ModelForm):
    campaign = forms.ModelChoiceField(queryset=Campaign.objects.none())

    def __init__(self, *args, **kwargs):
        workspace = kwargs.pop("workspace", None)
        super().__init__(*args, **kwargs)
        if workspace is not None:
            self.fields["campaign"].queryset = Campaign.objects.filter(workspace=workspace)

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
