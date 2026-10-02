import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from core.models import Campaign

User = get_user_model()


@pytest.mark.django_db
def test_dashboard_redirects_anonymous_user_to_sign_in(client):
    response = client.get(reverse("dashboard"))

    assert response.status_code == 302
    assert response.url.startswith(reverse("login"))


@pytest.mark.django_db
def test_user_can_sign_in_and_view_dashboard(client):
    User.objects.create_user(username="mira", password="A-safe-password-123")

    response = client.post(
        reverse("login"),
        {"username": "mira", "password": "A-safe-password-123"},
    )

    assert response.status_code == 302
    assert response.url == reverse("dashboard")
    assert client.get(reverse("dashboard")).status_code == 200


@pytest.mark.django_db
def test_invalid_credentials_do_not_sign_user_in(client):
    User.objects.create_user(username="mira", password="A-safe-password-123")

    response = client.post(
        reverse("login"),
        {"username": "mira", "password": "incorrect-password"},
    )

    assert response.status_code == 200
    assert b"correct username and password" in response.content
    assert not response.wsgi_request.user.is_authenticated


@pytest.mark.django_db
def test_logout_ends_the_session(client):
    user = User.objects.create_user(username="mira", password="A-safe-password-123")
    client.force_login(user)

    response = client.post(reverse("logout"))

    assert response.status_code == 302
    assert response.url == reverse("login")
    assert client.get(reverse("dashboard")).status_code == 302


@pytest.mark.django_db
def test_dashboard_shows_only_the_signed_in_users_campaigns(client):
    owner = User.objects.create_user(username="owner", password="A-safe-password-123")
    other_user = User.objects.create_user(username="other", password="A-safe-password-123")
    Campaign.objects.create(
        owner=owner,
        name="My campaign",
        website_url="https://example.com",
        target_keyword="organic growth",
    )
    Campaign.objects.create(
        owner=other_user,
        name="Private campaign",
        website_url="https://private.example",
        target_keyword="private keyword",
    )
    client.force_login(owner)

    response = client.get(reverse("dashboard"))

    assert response.status_code == 200
    assert b"My campaign" in response.content
    assert b"Private campaign" not in response.content
    assert response.context["total_campaigns"] == 1


@pytest.mark.django_db
def test_campaign_creation_assigns_the_signed_in_user(client):
    user = User.objects.create_user(username="mira", password="A-safe-password-123")
    client.force_login(user)

    response = client.post(
        reverse("campaign_create"),
        {
            "name": "Spring launch",
            "website_url": "https://example.com",
            "target_keyword": "sustainable skincare",
            "status": Campaign.Status.DRAFT,
        },
    )

    campaign = Campaign.objects.get(name="Spring launch")
    assert response.status_code == 302
    assert response.url == reverse("dashboard")
    assert campaign.owner == user


@pytest.mark.django_db
def test_campaign_creation_rejects_invalid_website_url(client):
    user = User.objects.create_user(username="mira", password="A-safe-password-123")
    client.force_login(user)

    response = client.post(
        reverse("campaign_create"),
        {
            "name": "Spring launch",
            "website_url": "not-a-url",
            "target_keyword": "sustainable skincare",
            "status": Campaign.Status.DRAFT,
        },
    )

    assert response.status_code == 200
    assert b"Enter a valid URL" in response.content
    assert Campaign.objects.count() == 0
