"""Set up a **custom Entra OAuth app** for WorkIQ identity passthrough.

Foundry authenticates a hosted agent to an Agent 365 WorkIQ MCP server with
**OAuth identity passthrough**. A plain "custom keys" bearer token does *not*
work: Foundry refuses to forward a Microsoft-audience token to the WorkIQ
endpoint ("Cannot pass Microsoft token to untrusted MCP endpoint"). Instead you
must bring **your own** Entra app registration and configure a custom-OAuth
Foundry connection against it.

This script automates the scriptable half of that setup:

  1. Resolves the delegated scope id for ``WORKIQ_SCOPE`` on the Agent 365 Tools
     app (``ea9ffc3e-8a23-4a7d-836d-234d7c7565c1``).
  2. Creates (or reuses) an Entra app registration + service principal.
  3. Adds the WorkIQ delegated permission and grants tenant admin consent.
  4. Creates a client secret.
  5. Prints the exact field values to paste into the Foundry **Custom > MCP >
     OAuth Identity Passthrough** connection dialog.

The one step that cannot be scripted is the connection's redirect-URL handshake:
Foundry issues a redirect URL only *after* you create the connection, and you
must add that URL back to this app. The script prints where to do that.

Requires: tenant admin (to grant admin consent) and the Azure CLI (``az login``).

Environment variables:
  WORKIQ_OAUTH_APP_NAME   App registration display name (default: marketing-workiq-oauth).
  WORKIQ_SCOPE            Delegated scope value to request (default:
                          McpServers.Calendar.All). Must be a scope exposed by
                          the Agent 365 Tools app — there is no
                          "McpServers.WorkIQ.All"; pick the specific capability
                          (Calendar, Mail, OneDriveSharepoint, Me, Teams, Word …).
  WORKIQ_TENANT_ID       Entra tenant id (falls back to AZURE_TENANT_ID, then az).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass

from scripts._cli import normalize
from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(dotenv_path=_REPO_ROOT / ".env", override=True)
load_dotenv(override=False)

# Agent 365 Tools ("Agent Tools") — the shared V1 audience that exposes the
# delegated McpServers.*.All scopes for the WorkIQ MCP servers.
ATG_APP_ID = "ea9ffc3e-8a23-4a7d-836d-234d7c7565c1"

APP_NAME = os.getenv("WORKIQ_OAUTH_APP_NAME", "marketing-workiq-oauth")
WORKIQ_SCOPE = os.getenv("WORKIQ_SCOPE", "McpServers.Calendar.All").strip()


def _az(*args: str, check: bool = True) -> str:
    """Run an ``az`` command and return trimmed stdout."""
    result = subprocess.run(
        normalize(["az", *args]), check=False, capture_output=True, text=True
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"az {' '.join(args)} failed ({result.returncode}): "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    return result.stdout.strip()


def _resolve_tenant_id() -> str:
    tenant = (
        os.getenv("WORKIQ_TENANT_ID", "").strip()
        or os.getenv("AZURE_TENANT_ID", "").strip()
    )
    if tenant:
        return tenant
    return _az("account", "show", "--query", "tenantId", "-o", "tsv")


def _resolve_scope_id(scope_value: str) -> str:
    """Find the delegated permission (scope) id for ``scope_value`` on ATG."""
    scopes_json = _az(
        "ad", "sp", "show", "--id", ATG_APP_ID,
        "--query", "oauth2PermissionScopes", "-o", "json",
    )
    scopes = json.loads(scopes_json or "[]")
    for scope in scopes:
        if scope.get("value") == scope_value:
            return scope["id"]
    available = ", ".join(sorted(s["value"] for s in scopes if s.get("value")))
    raise RuntimeError(
        f"Scope '{scope_value}' is not exposed by the Agent 365 Tools app. "
        f"Set WORKIQ_SCOPE to one of: {available}"
    )


def _ensure_app(display_name: str) -> str:
    """Create the app registration if missing; return its appId."""
    existing = _az(
        "ad", "app", "list", "--display-name", display_name,
        "--query", "[0].appId", "-o", "tsv",
    )
    if existing:
        print(f"==> Reusing app registration '{display_name}' (appId {existing})")
        return existing
    app_id = _az(
        "ad", "app", "create", "--display-name", display_name,
        "--sign-in-audience", "AzureADMyOrg",
        "--query", "appId", "-o", "tsv",
    )
    print(f"==> Created app registration '{display_name}' (appId {app_id})")
    return app_id


def _ensure_service_principal(app_id: str) -> None:
    existing = _az(
        "ad", "sp", "list", "--filter", f"appId eq '{app_id}'",
        "--query", "[0].id", "-o", "tsv",
    )
    if existing:
        return
    _az("ad", "sp", "create", "--id", app_id)
    print("==> Created service principal for the app.")


def _add_permission(app_id: str, scope_id: str, scope_value: str = WORKIQ_SCOPE) -> None:
    _az(
        "ad", "app", "permission", "add",
        "--id", app_id,
        "--api", ATG_APP_ID,
        "--api-permissions", f"{scope_id}=Scope",
    )
    print(f"==> Added delegated permission {scope_value} on Agent 365 Tools.")


def _admin_consent(app_id: str) -> None:
    try:
        _az("ad", "app", "permission", "admin-consent", "--id", app_id)
        print("==> Granted tenant admin consent.")
    except RuntimeError as exc:
        print(
            "WARNING: admin consent failed — grant it manually in the Entra "
            "admin center (API permissions > Grant admin consent).\n"
            f"  Detail: {exc}"
        )


def _create_secret(app_id: str) -> str:
    return _az(
        "ad", "app", "credential", "reset",
        "--id", app_id, "--append", "--display-name", "foundry-workiq-oauth",
        "--query", "password", "-o", "tsv",
    )


@dataclass
class WorkIQOAuthApp:
    """The scriptable outputs needed to configure the Foundry OAuth connection."""

    app_id: str
    client_secret: str
    tenant_id: str
    scope: str
    scopes: str
    authority: str

    @property
    def auth_url(self) -> str:
        return f"{self.authority}/authorize"

    @property
    def token_url(self) -> str:
        return f"{self.authority}/token"

    @property
    def refresh_url(self) -> str:
        return f"{self.authority}/token"


def ensure_oauth_app(
    display_name: str = APP_NAME, scope: str = WORKIQ_SCOPE
) -> WorkIQOAuthApp:
    """Create/reuse the custom Entra OAuth app and return its connection config.

    Idempotently ensures the app registration, service principal, WorkIQ
    delegated permission and admin consent, then mints a fresh client secret.
    Callers (e.g. scripts.create_workiq_connection) use the returned values to
    build the Foundry custom-OAuth connection without the portal.
    """
    tenant_id = _resolve_tenant_id()
    scope_id = _resolve_scope_id(scope)
    app_id = _ensure_app(display_name)
    _ensure_service_principal(app_id)
    _add_permission(app_id, scope_id, scope)
    _admin_consent(app_id)
    secret = _create_secret(app_id)
    return WorkIQOAuthApp(
        app_id=app_id,
        client_secret=secret,
        tenant_id=tenant_id,
        scope=scope,
        scopes=f"{ATG_APP_ID}/{scope} offline_access",
        authority=f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0",
    )


def append_redirect_uri(app_id: str, redirect_uri: str) -> bool:
    """Add ``redirect_uri`` to the app's Web redirect URIs (idempotent).

    Foundry issues its OAuth callback URL when the connection is created; adding
    it here lets the identity-passthrough consent complete. Returns True if the
    URI was added, False if it was already present.
    """
    existing = json.loads(
        _az("ad", "app", "show", "--id", app_id,
            "--query", "web.redirectUris", "-o", "json") or "[]"
    )
    if redirect_uri in existing:
        return False
    _az("ad", "app", "update", "--id", app_id,
        "--web-redirect-uris", *existing, redirect_uri)
    return True


def main() -> None:
    app = ensure_oauth_app()

    print("\n" + "=" * 72)
    print("Custom OAuth app ready. Create the Foundry connection with these values")
    print("(Foundry portal > your project > Tools > Add tool > Custom > MCP >")
    print(" OAuth Identity Passthrough > Custom OAuth):")
    print("=" * 72)
    print("  Connection name : workiq-connection")
    print("  MCP server URL  : (the tenant-scoped WorkIQ URL you registered)")
    print(f"  Client ID       : {app.app_id}")
    print(f"  Client secret   : {app.client_secret}")
    print(f"  Auth URL        : {app.auth_url}")
    print(f"  Token URL       : {app.token_url}")
    print(f"  Refresh URL     : {app.refresh_url}")
    print(f"  Scopes          : {app.scopes}")
    print("=" * 72)
    print(
        "Prefer to skip the portal? Run instead:\n"
        "  python -m scripts.create_workiq_connection\n"
        "which creates the connection with 'azd ai connection create' and\n"
        "re-registers the toolbox for you.\n"
    )
    print(
        "After you save the connection, Foundry shows a redirect URL. Add it to\n"
        f"this app (Entra admin center > App registrations > {APP_NAME} >\n"
        "Authentication > Add a platform > Web > Redirect URIs), then finish the\n"
        "connection. Finally re-register the toolbox against the connection:\n"
        "  WORKIQ_CONNECTION_NAME=workiq-connection python -m scripts.register_workiq_toolbox\n"
    )
    print(
        "NOTE: the client secret above is shown once. Store it securely; it is\n"
        "only needed to configure the Foundry connection."
    )


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
