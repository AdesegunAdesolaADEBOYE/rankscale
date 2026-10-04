from core.models import Workspace, WorkspaceMember


def accessible_workspaces(user):
    Workspace.ensure_for_user(user)
    for workspace in Workspace.objects.filter(owner=user):
        WorkspaceMember.objects.get_or_create(
            workspace=workspace,
            user=user,
            defaults={"role": WorkspaceMember.Role.OWNER},
        )
    return Workspace.objects.filter(members__user=user).distinct()


def current_workspace(request):
    workspaces = accessible_workspaces(request.user)
    workspace_id = request.session.get("workspace_id")
    if workspace_id:
        workspace = workspaces.filter(pk=workspace_id).first()
        if workspace:
            return workspace
    workspace = workspaces.order_by("created_at", "pk").first()
    request.session["workspace_id"] = workspace.pk
    return workspace


def user_workspace_role(user, workspace):
    return WorkspaceMember.objects.filter(
        user=user,
        workspace=workspace,
    ).values_list("role", flat=True).first()


def can_manage_workspace(user, workspace):
    return user_workspace_role(user, workspace) in (
        WorkspaceMember.Role.OWNER,
        WorkspaceMember.Role.ADMIN,
    )
