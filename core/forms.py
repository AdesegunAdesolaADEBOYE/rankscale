from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from core.models import Campaign


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
