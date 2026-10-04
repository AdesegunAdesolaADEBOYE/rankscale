import pytest
from datetime import timedelta
from django.utils import timezone
from django.core import mail
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse

from core.models import Campaign, Workspace, WorkspaceInvitation, WorkspaceMember

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


@pytest.mark.django_db
def test_user_can_create_a_content_template(client):
    user = User.objects.create_user(username="mira", password="A-safe-password-123")
    client.force_login(user)

    response = client.post(
        reverse("content_templates"),
        {
            "title": "Spring landing page",
            "slug": "spring-landing-page",
            "category": "landing_page",
            "description": "Hero copy for the product launch.",
            "content": "Welcome to {{ campaign_name }}. We help {{ target_keyword }} growth.",
            "variables": "campaign_name, target_keyword",
        },
    )

    assert response.status_code == 302
    assert response.url == reverse("content_templates")
    assert user.workspaces.count() == 1
    assert user.workspaces.first().content_templates.count() == 1


@pytest.mark.django_db
def test_template_variable_editor_detects_placeholders_and_updates_definitions(client):
    user = User.objects.create_user(username="mira", password="A-safe-password-123")
    client.force_login(user)
    response = client.post(
        reverse("content_templates"),
        {
            "title": "Variable landing page",
            "slug": "variable-landing-page",
            "category": "landing_page",
            "description": "Editable campaign copy.",
            "content": "Welcome {{ headline }}. Discover {{ target_keyword }}.",
            "variables": "headline | Main headline | Make a better choice | required",
        },
    )
    assert response.status_code == 302
    template = user.workspaces.first().content_templates.get()
    assert template.variables == [
        {
            "name": "headline",
            "label": "Main headline",
            "default": "Make a better choice",
            "required": True,
        }
    ]
    assert reverse(
        "content_template_edit",
        args=[template.pk],
    ) in client.get(reverse("content_templates")).content.decode()

    response = client.get(reverse("content_template_edit", args=[template.pk]))
    assert response.status_code == 200
    response = client.post(
        reverse("content_template_edit", args=[template.pk]),
        {
            "title": template.title,
            "slug": template.slug,
            "category": template.category,
            "description": template.description,
            "content": "Try {{ headline }}. Ask us about {{ offer }}.",
            "variables": (
                "headline | Updated heading | Start growing | required\n"
                "offer | Offer | Free audit | optional"
            ),
        },
    )
    assert response.status_code == 302
    template.refresh_from_db()
    assert [item["name"] for item in template.variables] == ["headline", "offer"]
    assert template.variables[1]["default"] == "Free audit"


@pytest.mark.django_db
def test_user_can_generate_a_page_and_capture_a_lead(client):
    user = User.objects.create_user(username="mira", password="A-safe-password-123")
    campaign = Campaign.objects.create(
        owner=user,
        name="Spring launch",
        website_url="https://example.com",
        target_keyword="sustainable skincare",
    )
    template = campaign.workspace.content_templates.create(
        title="Launch template",
        slug="launch-template",
        category="landing_page",
        content="Hello {{ campaign_name }}. Search for {{ target_keyword }} today.",
        variables=["campaign_name", "target_keyword"],
    )
    client.force_login(user)

    page_response = client.post(
        reverse("generated_pages"),
        {
            "campaign": campaign.id,
            "title": "Launch page",
            "slug": "launch-page",
            "template": template.id,
            "status": "draft",
        },
    )
    lead_response = client.post(
        reverse("leads"),
        {
            "campaign": campaign.id,
            "full_name": "Nina Patel",
            "email": "nina@example.com",
            "company": "Northstar Labs",
            "source": "website",
            "notes": "Interested in a discovery call.",
        },
    )

    assert page_response.status_code == 302
    assert lead_response.status_code == 302
    assert campaign.pages.filter(title="Launch page").count() == 1
    assert campaign.leads.filter(email="nina@example.com").count() == 1


@pytest.mark.django_db
def test_generated_page_uses_template_variables_and_campaign_values(client):
    user = User.objects.create_user(username="mira", password="A-safe-password-123")
    campaign = Campaign.objects.create(
        owner=user,
        name="Spring launch",
        website_url="https://example.com",
        target_keyword="sustainable skincare",
    )
    template = campaign.workspace.content_templates.create(
        title="Editable landing page",
        slug="editable-landing-page",
        category="landing_page",
        content=(
            "{{ headline }} for {{ campaign_name }}. "
            "Find {{ target_keyword }}. {{ offer }}"
        ),
        variables=[
            {
                "name": "headline",
                "label": "Headline",
                "default": "Grow with us",
                "required": True,
            },
            {
                "name": "offer",
                "label": "Offer",
                "default": "Free consultation",
                "required": False,
            },
        ],
    )
    client.force_login(user)

    response = client.get(reverse("generated_pages"), {"template": template.pk})
    assert response.status_code == 200
    assert b'name="variable_headline"' in response.content
    assert b'value="Grow with us"' in response.content

    response = client.post(
        reverse("generated_pages"),
        {
            "campaign": campaign.pk,
            "title": "Spring page",
            "slug": "spring-page",
            "template": template.pk,
            "status": "draft",
            "variable_headline": "Care for your skin",
            "variable_offer": "A free routine consultation",
        },
    )
    assert response.status_code == 302
    page = campaign.pages.get(slug="spring-page")
    assert page.variable_values == {
        "headline": "Care for your skin",
        "offer": "A free routine consultation",
    }
    assert page.content == (
        "Care for your skin for Spring launch. "
        "Find sustainable skincare. A free routine consultation"
    )

    response = client.post(
        reverse("generated_pages"),
        {
            "campaign": campaign.pk,
            "title": "Invalid page",
            "slug": "invalid-page",
            "template": template.pk,
            "status": "draft",
            "variable_offer": "Offer only",
        },
    )
    assert response.status_code == 200
    assert b"This field is required." in response.content
    assert not campaign.pages.filter(slug="invalid-page").exists()


@pytest.mark.django_db
def test_template_editor_and_page_form_are_workspace_scoped(client):
    owner = User.objects.create_user(username="owner", password="A-safe-password-123")
    outsider = User.objects.create_user(username="outsider", password="A-safe-password-123")
    campaign = Campaign.objects.create(
        owner=owner,
        name="Private campaign",
        website_url="https://example.com",
        target_keyword="private",
    )
    template = campaign.workspace.content_templates.create(
        title="Private template",
        slug="private-template",
        content="Private {{ phrase }}",
        variables=[
            {"name": "phrase", "label": "Phrase", "default": "", "required": False}
        ],
    )
    client.force_login(outsider)
    assert client.get(
        reverse("content_template_edit", args=[template.pk])
    ).status_code == 404
    response = client.get(reverse("generated_pages"), {"template": template.pk})
    assert response.status_code == 200
    assert b"name=\"variable_phrase\"" not in response.content


@pytest.mark.django_db
def test_workspace_members_share_campaigns_but_other_users_do_not(client):
    owner = User.objects.create_user(username="owner", password="A-safe-password-123")
    teammate = User.objects.create_user(username="teammate", password="A-safe-password-123")
    outsider = User.objects.create_user(username="outsider", password="A-safe-password-123")
    workspace = Workspace.objects.create(owner=owner, name="Acme team")
    WorkspaceMember.objects.create(
        workspace=workspace,
        user=owner,
        role=WorkspaceMember.Role.OWNER,
    )
    WorkspaceMember.objects.create(
        workspace=workspace,
        user=teammate,
        role=WorkspaceMember.Role.MEMBER,
    )
    campaign = Campaign.objects.create(
        owner=owner,
        workspace=workspace,
        name="Shared campaign",
        website_url="https://example.com",
        target_keyword="team keyword",
    )

    client.force_login(teammate)
    response = client.get(reverse("dashboard"))
    assert response.status_code == 200
    assert b"Shared campaign" in response.content
    assert response.context["total_campaigns"] == 1

    client.force_login(outsider)
    response = client.get(reverse("dashboard"))
    assert response.status_code == 200
    assert b"Shared campaign" not in response.content
    assert response.context["total_campaigns"] == 0
    assert client.get(reverse("campaign_datasets", args=[campaign.id])).status_code == 404


@pytest.mark.django_db
@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_workspace_owner_can_create_workspace_and_invite_by_email(client):
    owner = User.objects.create_user(username="owner", password="A-safe-password-123")
    teammate = User.objects.create_user(username="teammate", password="A-safe-password-123")
    client.force_login(owner)

    response = client.post(
        reverse("workspace_settings"),
        {"action": "create", "name": "Acme SEO"},
    )
    workspace = Workspace.objects.get(name="Acme SEO")
    assert response.status_code == 302
    assert response.url == reverse("workspace_settings")
    assert WorkspaceMember.objects.get(
        workspace=workspace,
        user=owner,
    ).role == WorkspaceMember.Role.OWNER

    response = client.post(
        reverse("workspace_settings"),
        {
            "action": "invite",
            "email": "teammate@example.com",
            "role": WorkspaceMember.Role.ADMIN,
        },
    )
    assert response.status_code == 302
    invitation = WorkspaceInvitation.objects.get(workspace=workspace)
    assert invitation.email == "teammate@example.com"
    assert invitation.role == WorkspaceMember.Role.ADMIN
    assert invitation.status == WorkspaceInvitation.Status.PENDING
    assert len(mail.outbox) == 1
    assert str(invitation.token) in mail.outbox[0].body


@pytest.mark.django_db
def test_workspace_member_cannot_add_members_or_access_another_workspace(client):
    owner = User.objects.create_user(username="owner", password="A-safe-password-123")
    teammate = User.objects.create_user(username="teammate", password="A-safe-password-123")
    outsider = User.objects.create_user(username="outsider", password="A-safe-password-123")
    workspace = Workspace.objects.create(owner=owner, name="Private team")
    WorkspaceMember.objects.create(
        workspace=workspace,
        user=owner,
        role=WorkspaceMember.Role.OWNER,
    )
    WorkspaceMember.objects.create(
        workspace=workspace,
        user=teammate,
        role=WorkspaceMember.Role.MEMBER,
    )
    client.force_login(teammate)

    response = client.post(
        reverse("workspace_settings"),
        {
            "action": "invite",
            "email": "outsider@example.com",
            "role": WorkspaceMember.Role.MEMBER,
        },
    )
    assert response.status_code == 302
    assert not WorkspaceMember.objects.filter(
        workspace=workspace,
        user=outsider,
    ).exists()

    response = client.post(
        reverse("workspace_switch"),
        {"workspace_id": Workspace.objects.create(owner=outsider, name="Other").pk},
    )
    assert response.status_code == 404
    assert client.session["workspace_id"] == workspace.pk


@pytest.mark.django_db
def test_workspace_role_permissions_preserve_owner_and_admin_boundaries(client):
    owner = User.objects.create_user(username="owner", password="A-safe-password-123")
    admin = User.objects.create_user(username="admin", password="A-safe-password-123")
    teammate = User.objects.create_user(username="teammate", password="A-safe-password-123")
    new_user = User.objects.create_user(username="new-user", password="A-safe-password-123")
    workspace = Workspace.objects.create(owner=owner, name="Role test team")
    owner_member = WorkspaceMember.objects.create(
        workspace=workspace,
        user=owner,
        role=WorkspaceMember.Role.OWNER,
    )
    admin_member = WorkspaceMember.objects.create(
        workspace=workspace,
        user=admin,
        role=WorkspaceMember.Role.ADMIN,
    )
    teammate_member = WorkspaceMember.objects.create(
        workspace=workspace,
        user=teammate,
        role=WorkspaceMember.Role.MEMBER,
    )

    client.force_login(admin)
    response = client.post(
        reverse("workspace_settings"),
        {
            "action": "invite",
            "email": "new-user@example.com",
            "role": WorkspaceMember.Role.ADMIN,
        },
    )
    assert response.status_code == 200
    assert not WorkspaceInvitation.objects.filter(
        workspace=workspace,
        email="new-user@example.com",
    ).exists()

    response = client.post(
        reverse("workspace_member_remove", args=[admin_member.pk]),
    )
    assert response.status_code == 302
    assert WorkspaceMember.objects.filter(pk=admin_member.pk).exists()

    client.force_login(owner)
    response = client.post(
        reverse("workspace_member_remove", args=[owner_member.pk]),
    )
    assert response.status_code == 302
    assert WorkspaceMember.objects.filter(pk=owner_member.pk).exists()

    client.force_login(admin)
    response = client.post(
        reverse("workspace_member_remove", args=[teammate_member.pk]),
    )
    assert response.status_code == 302
    assert not WorkspaceMember.objects.filter(pk=teammate_member.pk).exists()
    assert WorkspaceMember.objects.filter(pk=admin_member.pk).exists()


@pytest.mark.django_db
@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_invited_user_must_match_email_and_confirm_before_joining(client):
    owner = User.objects.create_user(
        username="owner",
        email="owner@example.com",
        password="A-safe-password-123",
    )
    invitee = User.objects.create_user(
        username="invitee",
        email="invitee@example.com",
        password="A-safe-password-123",
    )
    workspace = Workspace.objects.create(owner=owner, name="Invite target")
    WorkspaceMember.objects.create(
        workspace=workspace,
        user=owner,
        role=WorkspaceMember.Role.OWNER,
    )
    client.force_login(owner)
    client.post(
        reverse("workspace_settings"),
        {
            "action": "invite",
            "email": invitee.email,
            "role": WorkspaceMember.Role.MEMBER,
        },
    )
    invitation = WorkspaceInvitation.objects.get(workspace=workspace)
    invite_url = reverse("workspace_invitation_accept", args=[invitation.token])

    client.force_login(invitee)
    response = client.get(invite_url)
    assert response.status_code == 200
    assert not WorkspaceMember.objects.filter(workspace=workspace, user=invitee).exists()

    response = client.post(invite_url)
    assert response.status_code == 302
    assert response.url == reverse("dashboard")
    assert WorkspaceMember.objects.get(workspace=workspace, user=invitee).role == WorkspaceMember.Role.MEMBER
    invitation.refresh_from_db()
    assert invitation.status == WorkspaceInvitation.Status.ACCEPTED
    assert invitation.accepted_at is not None
    assert client.session["workspace_id"] == workspace.pk


@pytest.mark.django_db
def test_new_invitee_can_sign_up_and_return_to_acceptance(client):
    owner = User.objects.create_user(
        username="owner",
        email="owner@example.com",
        password="A-safe-password-123",
    )
    workspace = Workspace.objects.create(owner=owner, name="New account invitation")
    WorkspaceMember.objects.create(
        workspace=workspace,
        user=owner,
        role=WorkspaceMember.Role.OWNER,
    )
    invitation = WorkspaceInvitation.objects.create(
        workspace=workspace,
        email="new-invitee@example.com",
        role=WorkspaceMember.Role.MEMBER,
        invited_by=owner,
        expires_at=timezone.now() + timedelta(days=7),
    )
    invite_url = reverse("workspace_invitation_accept", args=[invitation.token])

    response = client.get(invite_url)
    assert response.status_code == 302
    login_url = response.url
    response = client.get(login_url)
    assert response.status_code == 200
    assert b"signup" in response.content

    signup_url = reverse("signup")
    response = client.get(signup_url, {"next": invite_url})
    assert response.status_code == 200
    response = client.post(
        signup_url,
        {
            "next": invite_url,
            "username": "new-invitee",
            "email": "new-invitee@example.com",
            "first_name": "",
            "last_name": "",
            "password1": "A-strong-password-938!",
            "password2": "A-strong-password-938!",
        },
    )
    assert response.status_code == 302
    assert response.url == invite_url
    assert client.get(invite_url).status_code == 200
    response = client.post(invite_url)
    assert response.status_code == 302
    invitee = User.objects.get(username="new-invitee")
    assert WorkspaceMember.objects.filter(
        workspace=workspace,
        user=invitee,
        role=WorkspaceMember.Role.MEMBER,
    ).exists()


@pytest.mark.django_db
def test_invitation_cannot_be_accepted_by_another_email_or_after_expiration(client):
    owner = User.objects.create_user(username="owner", email="owner@example.com", password="A-safe-password-123")
    invitee = User.objects.create_user(username="invitee", email="invitee@example.com", password="A-safe-password-123")
    other = User.objects.create_user(username="other", email="other@example.com", password="A-safe-password-123")
    workspace = Workspace.objects.create(owner=owner, name="Invite security")
    WorkspaceMember.objects.create(workspace=workspace, user=owner, role=WorkspaceMember.Role.OWNER)
    expired_invitation = WorkspaceInvitation.objects.create(
        workspace=workspace,
        email=invitee.email,
        role=WorkspaceMember.Role.MEMBER,
        invited_by=owner,
        expires_at=timezone.now() + timedelta(days=1),
    )
    client.force_login(other)
    response = client.get(
        reverse("workspace_invitation_accept", args=[expired_invitation.token])
    )
    assert response.status_code == 403

    expired_invitation.expires_at = timezone.now() - timedelta(seconds=1)
    expired_invitation.save(update_fields=("expires_at",))
    client.force_login(invitee)
    response = client.get(
        reverse("workspace_invitation_accept", args=[expired_invitation.token])
    )
    assert response.status_code == 302
    expired_invitation.refresh_from_db()
    assert expired_invitation.status == WorkspaceInvitation.Status.REVOKED
    assert not WorkspaceMember.objects.filter(workspace=workspace, user=invitee).exists()


@pytest.mark.django_db
def test_owner_can_edit_roles_and_admin_cannot_promote_members(client):
    owner = User.objects.create_user(username="owner", password="A-safe-password-123")
    admin = User.objects.create_user(username="admin", password="A-safe-password-123")
    member = User.objects.create_user(username="member", password="A-safe-password-123")
    workspace = Workspace.objects.create(owner=owner, name="Role editing")
    WorkspaceMember.objects.create(workspace=workspace, user=owner, role=WorkspaceMember.Role.OWNER)
    WorkspaceMember.objects.create(workspace=workspace, user=admin, role=WorkspaceMember.Role.ADMIN)
    member_record = WorkspaceMember.objects.create(
        workspace=workspace,
        user=member,
        role=WorkspaceMember.Role.MEMBER,
    )

    client.force_login(admin)
    response = client.post(
        reverse("workspace_settings"),
        {
            "action": "edit_member",
            "member_id": member_record.pk,
            "role": WorkspaceMember.Role.ADMIN,
        },
    )
    assert response.status_code == 302
    member_record.refresh_from_db()
    assert member_record.role == WorkspaceMember.Role.MEMBER

    client.force_login(owner)
    response = client.post(
        reverse("workspace_settings"),
        {
            "action": "edit_member",
            "member_id": member_record.pk,
            "role": WorkspaceMember.Role.ADMIN,
        },
    )
    assert response.status_code == 302
    member_record.refresh_from_db()
    assert member_record.role == WorkspaceMember.Role.ADMIN


@pytest.mark.django_db
def test_workspace_owner_can_transfer_ownership_to_a_member(client):
    owner = User.objects.create_user(username="owner", password="A-safe-password-123")
    teammate = User.objects.create_user(username="teammate", password="A-safe-password-123")
    workspace = Workspace.objects.create(owner=owner, name="Ownership transfer")
    old_owner = WorkspaceMember.objects.create(
        workspace=workspace,
        user=owner,
        role=WorkspaceMember.Role.OWNER,
    )
    new_owner = WorkspaceMember.objects.create(
        workspace=workspace,
        user=teammate,
        role=WorkspaceMember.Role.MEMBER,
    )
    client.force_login(owner)

    response = client.post(
        reverse("workspace_settings"),
        {"action": "transfer", "new_owner": new_owner.pk},
    )

    assert response.status_code == 302
    workspace.refresh_from_db()
    old_owner.refresh_from_db()
    new_owner.refresh_from_db()
    assert workspace.owner == teammate
    assert old_owner.role == WorkspaceMember.Role.ADMIN
    assert new_owner.role == WorkspaceMember.Role.OWNER


@pytest.mark.django_db
def test_workspace_deletion_requires_owner_and_exact_name(client):
    owner = User.objects.create_user(username="owner", password="A-safe-password-123")
    member = User.objects.create_user(username="member", password="A-safe-password-123")
    workspace = Workspace.objects.create(owner=owner, name="Delete carefully")
    WorkspaceMember.objects.create(workspace=workspace, user=owner, role=WorkspaceMember.Role.OWNER)
    WorkspaceMember.objects.create(workspace=workspace, user=member, role=WorkspaceMember.Role.MEMBER)
    campaign = Campaign.objects.create(
        owner=owner,
        workspace=workspace,
        name="Cascade data",
        website_url="https://example.com",
        target_keyword="test",
    )
    client.force_login(member)
    response = client.post(
        reverse("workspace_settings"),
        {"action": "delete", "confirmation": workspace.name},
    )
    assert response.status_code == 302
    assert Workspace.objects.filter(pk=workspace.pk).exists()
    assert campaign.workspace_id == workspace.pk

    client.force_login(owner)
    response = client.post(
        reverse("workspace_settings"),
        {"action": "delete", "confirmation": "wrong name"},
    )
    assert response.status_code == 200
    assert Workspace.objects.filter(pk=workspace.pk).exists()

    response = client.post(
        reverse("workspace_settings"),
        {"action": "delete", "confirmation": workspace.name},
    )
    assert response.status_code == 302
    assert not Workspace.objects.filter(pk=workspace.pk).exists()
    assert not Campaign.objects.filter(pk=campaign.pk).exists()
