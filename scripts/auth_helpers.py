"""Shared helpers for **Entra ID authentication** on the marketing MCP servers.

The MCP-server Container Apps validate incoming Entra access tokens **inside the
app** using FastMCP's Azure JWT verifier (issuer + audience + JWKS signature) —
no Container Apps Easy Auth. These helpers manage the Entra **app registration**
that backs each server (the audience callers request a token for) and the
``Mcp.Invoke`` app role granted to the calling agents. Everything is gated by a
single environment variable so it can be toggled per deployment:

    ENTRA_AUTH_ENABLED   "true"/"false" (default: true)

When ``true`` the deploy scripts:

* ensure an Entra **app registration** exists for each MCP server (the audience
  callers request a token for — ``api://<appId>``), with an ``Mcp.Invoke``
  application role and a ``requestedAccessTokenVersion = 2`` API surface;
* pass the audience client id + tenant to the MCP container so FastMCP enforces
  Entra JWT validation at runtime (unauthenticated requests get HTTP 401);
* grant the calling agents' identities the ``Mcp.Invoke`` app role so they can
  acquire tokens for the MCP audience.

When ``false`` the servers run anonymously (no auth env — local-dev friendly).

Everything is idempotent and best-effort: the app registration is looked up by
display name before being created and role assignments swallow "already exists"
errors. All commands go through the Azure CLI (``az``) so no extra Python SDK is
needed by the container-app deploy scripts.
"""

from __future__ import annotations

import json
import os
import subprocess
import time

from scripts._cli import normalize

# Stable identifier for the application role granted to calling agents. Using a
# fixed GUID keeps re-runs idempotent (the role is matched by id, not name).
MCP_INVOKE_ROLE_ID = "b9f4a1e2-3c5d-4a7b-8e6f-1d2c3b4a5e6f"
MCP_INVOKE_ROLE_VALUE = "Mcp.Invoke"

# Stable identifier for the delegated (user) scope exposed on the app so any
# tenant user can also acquire a token. Fixed GUID keeps re-runs idempotent.
MCP_USER_SCOPE_ID = "a1b2c3d4-5e6f-4a1b-9c2d-3e4f5a6b7c8d"

# Well-known first-party appId of the Azure CLI, pre-authorized on the API so a
# signed-in user can mint a token for testing (az account get-access-token).
AZURE_CLI_APP_ID = "04b07795-8ddb-461a-bbee-02f9e1bf7b46"


def entra_auth_enabled() -> bool:
    """Return ``True`` when ``ENTRA_AUTH_ENABLED`` is set to a truthy value.

    Defaults to ``True`` so the MCP servers are protected with Entra ID unless a
    deployment explicitly opts out with ``ENTRA_AUTH_ENABLED=false``.
    """
    return os.getenv("ENTRA_AUTH_ENABLED", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _az(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(normalize(args), check=False, capture_output=True, text=True)
    if check and result.returncode != 0:
        stderr = (result.stderr or "").strip()
        raise RuntimeError(
            f"Command failed ({result.returncode}): {' '.join(args)}\n{stderr}"
        )
    return result


def resolve_tenant_id() -> str:
    """Resolve the Entra tenant id (env override, else the signed-in ``az`` tenant)."""
    tenant = (
        os.getenv("AZURE_TENANT_ID", "").strip()
        or os.getenv("ENTRA_AUTH_TENANT_ID", "").strip()
    )
    if tenant:
        return tenant
    result = _az(["az", "account", "show", "--query", "tenantId", "-o", "tsv"], check=False)
    tenant = result.stdout.strip()
    if not tenant:
        raise RuntimeError(
            "Could not resolve the Entra tenant id. Set AZURE_TENANT_ID in ./.env "
            "or sign in with 'az login'."
        )
    return tenant


def auth_app_display_name(app_name: str) -> str:
    """Deterministic app-registration display name for an MCP Container App.

    Both the MCP deploy script (which creates it) and the consuming-agent deploy
    script (which looks it up to pass the audience/grant the role) derive the
    same name from the Container App name so they stay in sync.
    """
    return f"{app_name}-mcp-auth"


def _find_app_id(display_name: str) -> str:
    """Return the appId of an existing app registration, or "" if none."""
    result = _az(
        ["az", "ad", "app", "list", "--display-name", display_name,
         "--query", "[0].appId", "-o", "tsv"],
        check=False,
    )
    return result.stdout.strip()


def ensure_mcp_app_registration(app_name: str) -> tuple[str, str]:
    """Ensure the Entra app registration backing an MCP server exists.

    Idempotent: the registration is looked up by display name and only created
    when missing. It exposes the identifier URI ``api://<appId>`` (the token
    audience callers request), a ``user_impersonation`` delegated scope (so any
    tenant **user** can obtain a token) and an ``Mcp.Invoke`` application role
    (so any tenant **app** can be granted an app-only token).

    Returns ``(app_id, audience)`` where ``audience`` is ``api://<app_id>``.
    """
    display_name = auth_app_display_name(app_name)
    app_id = _find_app_id(display_name)

    app_role = {
        "allowedMemberTypes": ["Application"],
        "description": "Callers may invoke the MCP server tools.",
        "displayName": "Invoke MCP tools",
        "id": MCP_INVOKE_ROLE_ID,
        "isEnabled": True,
        "value": MCP_INVOKE_ROLE_VALUE,
    }

    if not app_id:
        print(f"==> Creating Entra app registration '{display_name}'")
        app_id = _az(
            ["az", "ad", "app", "create",
             "--display-name", display_name,
             "--sign-in-audience", "AzureADMyOrg",
             "--app-roles", json.dumps([app_role]),
             "--query", "appId", "-o", "tsv"],
        ).stdout.strip()
    else:
        print(f"==> Reusing Entra app registration '{display_name}' ({app_id})")

    audience = f"api://{app_id}"
    # Set the identifier URI so tokens can target api://<appId>. Idempotent.
    _az(
        ["az", "ad", "app", "update", "--id", app_id,
         "--identifier-uris", audience],
        check=False,
    )
    # Expose a delegated scope so interactive **users** can also acquire a token
    # (app-only callers work via api://<appId>/.default without a scope).
    _ensure_delegated_scope(app_id)
    # Ensure a service principal exists so the app role can be assigned.
    _az(["az", "ad", "sp", "create", "--id", app_id], check=False)
    return app_id, audience


def _ensure_delegated_scope(app_id: str) -> None:
    """Configure the app's API surface so users and apps get v2 tokens (idempotent)."""
    object_id = ""
    for attempt in range(12):
        object_id = _az(
            ["az", "ad", "app", "show", "--id", app_id, "--query", "id", "-o", "tsv"],
            check=False,
        ).stdout.strip()
        if object_id:
            break
        time.sleep(5)
    if not object_id:
        print(f"  WARN: app {app_id} not queryable yet; token version not set.")
        return
    scope = {
        "id": MCP_USER_SCOPE_ID,
        "adminConsentDescription": "Allow the app to access the MCP server on behalf of the signed-in user.",
        "adminConsentDisplayName": "Access the MCP server",
        "userConsentDescription": "Allow the app to access the MCP server on your behalf.",
        "userConsentDisplayName": "Access the MCP server",
        "value": "user_impersonation",
        "type": "User",
        "isEnabled": True,
    }
    step1 = json.dumps(
        {"api": {"requestedAccessTokenVersion": 2, "oauth2PermissionScopes": [scope]}}
    )
    url = f"https://graph.microsoft.com/v1.0/applications/{object_id}"
    ok = False
    for _ in range(6):
        result = _az(
            ["az", "rest", "--method", "patch", "--url", url,
             "--headers", "Content-Type=application/json", "--body", step1],
            check=False,
        )
        if result.returncode == 0:
            ok = True
            break
        time.sleep(5)
    if not ok:
        print(
            f"  WARN: could not set requestedAccessTokenVersion on {app_id}: "
            f"{(result.stderr or '').strip()}"
        )
        return
    step2 = json.dumps(
        {
            "api": {
                "requestedAccessTokenVersion": 2,
                "oauth2PermissionScopes": [scope],
                "preAuthorizedApplications": [
                    {
                        "appId": AZURE_CLI_APP_ID,
                        "delegatedPermissionIds": [MCP_USER_SCOPE_ID],
                    }
                ],
            }
        }
    )
    _az(
        ["az", "rest", "--method", "patch", "--url", url,
         "--headers", "Content-Type=application/json", "--body", step2],
        check=False,
    )


def resolve_mcp_audience(app_name: str) -> str:
    """Return the ``api://<appId>`` audience for an MCP server, or "" if unregistered."""
    app_id = _find_app_id(auth_app_display_name(app_name))
    return f"api://{app_id}" if app_id else ""


def delete_mcp_app_registration(app_name: str) -> None:
    """Delete the ``<app>-mcp-auth`` Entra app registration for an MCP server.

    Used by the cleanup script for a full teardown. Best-effort and idempotent.
    """
    display_name = auth_app_display_name(app_name)
    app_id = _find_app_id(display_name)
    if not app_id:
        print(f"  no app registration '{display_name}' to delete")
        return
    result = _az(["az", "ad", "app", "delete", "--id", app_id], check=False)
    if result.returncode == 0:
        print(f"  deleted app registration '{display_name}' ({app_id})")
    else:
        print(f"  WARN: could not delete '{display_name}': {(result.stderr or '').strip()}")


def grant_mcp_role_to_principal(app_id: str, principal_object_id: str) -> None:
    """Grant the ``Mcp.Invoke`` app role on the MCP app to a principal.

    ``principal_object_id`` is the object id of the calling agent's identity
    (e.g. the user-assigned managed identity's principal id). Best-effort and
    idempotent — "already assigned" errors are ignored.
    """
    if not app_id or not principal_object_id:
        return
    sp_object_id = _az(
        ["az", "ad", "sp", "show", "--id", app_id, "--query", "id", "-o", "tsv"],
        check=False,
    ).stdout.strip()
    if not sp_object_id:
        print(f"  WARN: no service principal for {app_id}; cannot grant Mcp.Invoke.")
        return
    body = json.dumps(
        {
            "principalId": principal_object_id,
            "resourceId": sp_object_id,
            "appRoleId": MCP_INVOKE_ROLE_ID,
        }
    )
    url = (
        "https://graph.microsoft.com/v1.0/servicePrincipals/"
        f"{principal_object_id}/appRoleAssignments"
    )
    result = _az(
        ["az", "rest", "--method", "post", "--url", url,
         "--headers", "Content-Type=application/json", "--body", body],
        check=False,
    )
    if result.returncode == 0:
        print(f"  granted Mcp.Invoke on {app_id} to {principal_object_id}")
    elif "already exists" in (result.stderr or "").lower() or "permission being assigned already exists" in (result.stderr or "").lower():
        print(f"  Mcp.Invoke already assigned on {app_id} to {principal_object_id}")
    else:
        print(f"  WARN: could not grant Mcp.Invoke: {(result.stderr or '').strip()}")
