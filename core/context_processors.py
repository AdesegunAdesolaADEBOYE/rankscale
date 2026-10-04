from core.models import WorkspaceMember
from core.workspaces import accessible_workspaces, current_workspace, user_workspace_role


def workspace_context(request):
    if not request.user.is_authenticated:
        return {}

    workspaces = accessible_workspaces(request.user)
    workspace = current_workspace(request)
    role = user_workspace_role(request.user, workspace)
    return {
        "available_workspaces": workspaces,
        "current_workspace": workspace,
        "current_workspace_role": role,
        "can_manage_current_workspace": role
        in (WorkspaceMember.Role.OWNER, WorkspaceMember.Role.ADMIN),
    }
