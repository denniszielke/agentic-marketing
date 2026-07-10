"""Create the Foundry **WorkIQ custom-OAuth connection** and wire up the toolbox.

Automates the manual Foundry-portal step from ``scripts/setup_workiq_oauth_app.py``.
Instead of pasting the OAuth values into the portal (Tools > Add tool > Custom >
MCP > OAuth Identity Passthrough), this creates the identity-passthrough
connection non-interactively and re-registers the WorkIQ toolbox against it.

Why not the azure-ai-projects SDK? The ``AIProjectClient.connections`` API is
read-only (``get`` / ``list`` only) as of azure-ai-projects 2.x — it cannot
create a connection. The scriptable path is the Foundry azd extension:
``azd ai connection create ... --auth-type oauth2`` accepts the full BYO-OAuth2
field set (client id/secret, authorize/token/refresh URLs, scopes), which is
exactly what the WorkIQ identity-passthrough connection needs.

Flow:
  1. Ensure the custom Entra OAuth app exists — app registration, service
     principal, WorkIQ delegated scope + admin consent, fresh client secret
     (delegates to ``scripts.setup_workiq_oauth_app.ensure_oauth_app``).
  2. Create (or ``--force`` replace) the Foundry connection
     (``kind=remote-tool``, ``auth-type=oauth2``) targeting the tenant-scoped
     WorkIQ MCP URL.
  3. Optionally append Foundry's redirect URI to the app registration
     (``WORKIQ_REDIRECT_URI`` env or ``--redirect-uri``). Foundry issues this
     URL when the connection is created; if you don't have it yet the script
     prints any URL found in the azd output and reminds you to add it.
  4. Re-register the WorkIQ toolbox against the connection
     (``scripts.register_workiq_toolbox``).

Prerequisites:
  - ``az login`` (tenant admin, to grant admin consent for the scope).
  - The Foundry azd extension: ``azd ext install microsoft.foundry``.
  - ``AZURE_AI_PROJECT_ENDPOINT`` in ``./.env`` (written by ``azd up``).

Usage::

    # create the connection and re-register the toolbox
    python -m scripts.create_workiq_connection

    # replace an existing connection and add Foundry's redirect URI in one go
    python -m scripts.create_workiq_connection --force \
        --redirect-uri https://<foundry-callback-url>

Environment variables:
  AZURE_AI_PROJECT_ENDPOINT   Foundry project endpoint (required).
  WORKIQ_CONNECTION_NAME      Connection name to create (default workiq-connection).
  WORKIQ_MCP_URL /            WorkIQ MCP target URL (see register_workiq_toolbox
  WORKIQ_MCP_SERVER /         for how the tenant-scoped URL is built).
  WORKIQ_TENANT_ID
  WORKIQ_OAUTH_APP_NAME /     Custom OAuth app name + delegated scope
  WORKIQ_SCOPE                (see setup_workiq_oauth_app).
  WORKIQ_REDIRECT_URI         Foundry redirect URI to add to the app (optional).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from scripts._cli import normalize

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(dotenv_path=_REPO_ROOT / ".env", override=True)
load_dotenv(override=False)

import os  # noqa: E402  (after dotenv load)

from scripts.register_workiq_toolbox import _resolve_workiq_url  # noqa: E402
from scripts.setup_workiq_oauth_app import (  # noqa: E402
    WorkIQOAuthApp,
    append_redirect_uri,
    ensure_oauth_app,
)

CONNECTION_NAME = os.getenv("WORKIQ_CONNECTION_NAME", "workiq-connection").strip()


def _azd(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(normalize(["azd", *args]), check=False, capture_output=True, text=True)


def _ensure_azd() -> bool:
    """Verify the azd CLI and the Foundry extension (``azd ai``) are available."""
    if shutil.which("azd") is None:
        print(
            "ERROR: the Azure Developer CLI (azd) is not installed. Install it, then "
            "run 'azd ext install microsoft.foundry'.",
            file=sys.stderr,
        )
        return False
    if _azd("ai", "-h").returncode != 0:
        print(
            "ERROR: the Foundry azd extension is missing. Install it with "
            "'azd ext install microsoft.foundry'.",
            file=sys.stderr,
        )
        return False
    return True


def _oauth_scopes(app: WorkIQOAuthApp) -> str:
    """Render the space-separated scope string as azd's comma-separated list."""
    return ",".join(part for part in app.scopes.split() if part)


def _create_connection(
    name: str, target: str, app: WorkIQOAuthApp, force: bool
) -> subprocess.CompletedProcess[str]:
    """Create the WorkIQ custom-OAuth remote-tool connection via azd."""
    args = [
        "ai", "connection", "create", name,
        "--kind", "remote-tool",
        "--target", target,
        "--auth-type", "oauth2",
        "--client-id", app.app_id,
        "--client-secret", app.client_secret,
        "--authorization-url", app.auth_url,
        "--token-url", app.token_url,
        "--refresh-url", app.refresh_url,
        "--scopes", _oauth_scopes(app),
        "--no-prompt",
    ]
    if force:
        args.append("--force")
    return _azd(*args)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true",
        help="Replace the connection if it already exists (azd upsert).",
    )
    parser.add_argument(
        "--redirect-uri",
        default=os.getenv("WORKIQ_REDIRECT_URI", "").strip(),
        help="Foundry redirect URI to add to the OAuth app registration.",
    )
    parser.add_argument(
        "--skip-toolbox", action="store_true",
        help="Do not re-register the WorkIQ toolbox after creating the connection.",
    )
    args = parser.parse_args(argv)

    project_endpoint = os.getenv("AZURE_AI_PROJECT_ENDPOINT", "").strip()
    if not project_endpoint:
        print("ERROR: AZURE_AI_PROJECT_ENDPOINT is required.", file=sys.stderr)
        return 1

    if not _ensure_azd():
        return 1

    target = _resolve_workiq_url()

    # 1. Ensure the custom Entra OAuth app (fresh secret each run).
    print("==> Ensuring the custom WorkIQ OAuth app registration")
    app = ensure_oauth_app()

    # 2. Optionally add Foundry's redirect URI to the app.
    if args.redirect_uri:
        added = append_redirect_uri(app.app_id, args.redirect_uri)
        print(
            f"==> {'Added' if added else 'Redirect URI already present:'} "
            f"{args.redirect_uri}"
        )

    # 3. Point azd at the project and create the connection.
    print(f"==> azd ai project set {project_endpoint}")
    proj = _azd("ai", "project", "set", project_endpoint)
    if proj.returncode != 0:
        print(
            f"ERROR: 'azd ai project set' failed: {(proj.stderr or proj.stdout).strip()}",
            file=sys.stderr,
        )
        return 1

    print(f"==> Creating connection '{CONNECTION_NAME}' -> {target}")
    result = _create_connection(CONNECTION_NAME, target, app, args.force)
    combined = f"{result.stdout}\n{result.stderr}"
    if result.returncode != 0:
        if "already exists" in combined.lower() or "conflict" in combined.lower():
            print(
                f"  '{CONNECTION_NAME}' already exists. Re-run with --force to "
                "replace it."
            )
        else:
            print(
                f"ERROR creating '{CONNECTION_NAME}': {(result.stderr or result.stdout).strip()}",
                file=sys.stderr,
            )
            return 1
    else:
        print(f"  created connection '{CONNECTION_NAME}'.")
    if result.stdout.strip():
        print(result.stdout.strip())

    # 4. Re-register the toolbox against the new connection.
    if not args.skip_toolbox:
        os.environ["WORKIQ_CONNECTION_NAME"] = CONNECTION_NAME
        print(f"\n==> Re-registering the WorkIQ toolbox against '{CONNECTION_NAME}'")
        from scripts.register_workiq_toolbox import deploy as register_toolbox
        register_toolbox()

    if not args.redirect_uri:
        print(
            "\nNOTE: if Foundry requires a redirect URI for the OAuth consent, add\n"
            "it to the app registration and re-run with --redirect-uri "
            "<foundry-callback-url>\n"
            f"(Entra admin center > App registrations > {app.app_id} >\n"
            "Authentication > Add a platform > Web > Redirect URIs)."
        )

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
