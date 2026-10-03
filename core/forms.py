from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.core.validators import FileExtensionValidator

from core.models import Campaign

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


class DatasetUploadForm(forms.Form):
    file = forms.FileField(
        label="CSV file",
        validators=[FileExtensionValidator(allowed_extensions=("csv",))],
        widget=forms.ClearableFileInput(attrs={"accept": ".csv,text/csv"}),
    )

    def clean_file(self):
        uploaded_file = self.cleaned_data["file"]
        if uploaded_file.size > MAX_DATASET_UPLOAD_SIZE:
            raise forms.ValidationError("Choose a CSV file smaller than 10 MB.")
        return uploaded_file
