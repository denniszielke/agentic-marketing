"""Provision the **credentials Copilot Studio needs to call the marketing
specialist over A2A** — via an OAuth 2.0 app registration *or* an Entra Agent
Identity.

Two authentication modes are supported (use either or both):

* **OAuth 2.0 (default)** — Copilot Studio authenticates outbound calls with the
  authorization-code flow using a confidential-client Entra **app registration**
  (client id + secret). This script creates/updates that app registration and
  prints the exact parameters to paste into Copilot Studio (see below).

* **Entra Agent Identity** (``--agent-identity-id``) — a Copilot Studio agent can
  instead present its own **Entra Agent Identity** (agentic auth, *no secret*).
  In that case the only thing needed is the **Foundry Agent Consumer** RBAC role
  on the project, granted to that identity. Pass the agent identity's app/object
  id (or set ``COPILOT_STUDIO_AGENT_IDS``); add ``--agent-identity-only`` to skip
  the OAuth app-registration/secret provisioning entirely.

Both modes issue tokens whose audience is the Azure AI data plane
(``https://ai.azure.com``) — the audience the Foundry A2A endpoint of the
specialist accepts. In OAuth mode the script prints these parameters to paste
into Copilot Studio:

    Client ID              the app registration's application (client) id
    Client secret          a freshly-minted secret value (shown once)
    Authorization URL      https://login.microsoftonline.com/<tenant>/oauth2/v2.0/authorize
    Token URL template     https://login.microsoftonline.com/<tenant>/oauth2/v2.0/token
    Refresh URL            https://login.microsoftonline.com/<tenant>/oauth2/v2.0/token
    Scopes                 https://ai.azure.com/user_impersonation offline_access
    Redirect URL           https://global.consent.azure-apim.net/redirect (Copilot Studio)

What it does (all idempotent):
  1. Ensure the confidential-client app registration exists (``AzureADMyOrg``),
     with the Copilot Studio **redirect URI** registered as a *web* platform URI.
     Copilot Studio appends a **connector-specific suffix** to its base redirect
     (``…/redirect/<connector-id>``) when you create the connection, so pass that
     exact URI with ``--redirect-uri`` (repeatable, merged, never clobbered) once
     Copilot Studio shows it — otherwise sign-in fails with ``AADSTS50011``.
  2. Add the **delegated** ``user_impersonation`` permission on the Azure AI
     resource (``https://ai.azure.com``) and grant tenant admin consent so the
     authorization-code flow can mint ``https://ai.azure.com`` tokens.
  3. Ensure a **service principal** for the app and mint a **client secret**.
  4. Grant the **Foundry Agent Consumer** RBAC role on the Foundry project so the
     caller is authorized on the specialist's A2A endpoint. The role is granted to
     the app's service principal (covers the app-only/client-credentials test in
     ``scripts.test_copilot_studio_a2a_auth``) and to the signed-in user (covers the
     interactive authorization-code flow you'll use from Copilot Studio). Add more
     principals with ``--grant-object-id``.
  5. Print an **agent description** built from the specialist's ``agentcard.json``
     (its description + skills) to paste into the Copilot Studio agent/tool.

Requires: Azure CLI signed in (``az login``) with rights to create app
registrations, app-role/permission grants and RBAC role assignments, and the
marketing specialist deployed (``scripts.deploy_marketing_specialist_agent``).

Usage::

    # OAuth 2.0 app registration (default)
    python -m scripts.create_copilot_studio_a2a_auth
    python -m scripts.create_copilot_studio_a2a_auth --app-name "marketing-a2a-copilot" --secret-years 2
    python -m scripts.create_copilot_studio_a2a_auth --grant-object-id <USER_OR_SP_OBJECT_ID>

    # Entra Agent Identity of the Copilot Studio agent (no secret)
    python -m scripts.create_copilot_studio_a2a_auth \\
        --agent-identity-id 6da8f969-1785-4559-804b-1d95e09f6544 --agent-identity-only

Fixing ``AADSTS50011`` (redirect URI mismatch): Copilot Studio appends a
connector-specific suffix to its base redirect when you create the connection,
e.g. ``https://global.consent.azure-apim.net/redirect/<connector-id>``. Sign-in
fails with ``AADSTS50011`` until that *exact* URI is registered on the app. Copy
the redirect URL Copilot Studio shows and re-run with ``--redirect-uri`` (it is
merged with the existing ones, never clobbered)::

    python -m scripts.create_copilot_studio_a2a_auth \\
        --redirect-uri "https://global.consent.azure-apim.net/redirect/<connector-id>"

Note: each run mints a **new** client secret (appended, not rotated) — use the
value printed by the latest run in Copilot Studio.

Environment variables:
  AZURE_AI_PROJECT_ENDPOINT            Foundry project endpoint (required, for the A2A URL banner).
  AZURE_AI_SPECIALIST_AGENT_NAME       Specialist agent name (default: marketing-specialist-agent).
  AZURE_AI_PROJECT_ID                  Full ARM resource id of the project (role-assignment scope).
                                       Derived from AZURE_SUBSCRIPTION_ID/AZURE_RESOURCE_GROUP/
                                       AZURE_AI_PROJECT_NAME + endpoint when unset.
  COPILOT_STUDIO_A2A_APP_NAME          App-registration display name (default: <specialist>-copilot-studio-a2a).
  COPILOT_STUDIO_REDIRECT_URI         Override the Copilot Studio redirect URI.
  COPILOT_STUDIO_AGENT_IDS             Comma-separated Copilot Studio agent identity
                                       identifiers (app id, object id or display name)
                                       to grant the Foundry Agent Consumer role.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

from scripts._cli import normalize

_REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(dotenv_path=_REPO_ROOT / ".env", override=True)
load_dotenv(override=False)

from scripts.auth_helpers import resolve_tenant_id  # noqa: E402  (after dotenv load)
from scripts.prompt_agent_helpers import a2a_base_url  # noqa: E402

# Azure AI data-plane resource ("Azure Machine Learning Services"). Its
# ``user_impersonation`` delegated scope yields tokens with audience
# ``https://ai.azure.com`` — the audience the Foundry A2A endpoint validates.
AZURE_AI_RESOURCE_APP_ID = "18a66f5f-dbdf-4c17-9dd7-1634712a9cbe"
AZURE_AI_AUDIENCE = "https://ai.azure.com"

# The redirect URI Copilot Studio (Power Platform) uses for generic OAuth 2.0.
DEFAULT_COPILOT_STUDIO_REDIRECT_URI = "https://global.consent.azure-apim.net/redirect"

# RBAC role that authorizes an identity to call a Foundry agent's A2A endpoint.
A2A_CALLER_ROLE = "Foundry Agent Consumer"

# The specialist's agent card — its description + skills seed the Copilot Studio
# agent/tool description.
DEFAULT_AGENT_CARD_PATH = "src/marketing_specialist_agent/agentcard.json"


def build_agent_description(card_path: str) -> str:
    """Build a Copilot Studio agent description from the specialist's agent card.

    Combines the card's ``description`` with a bulleted summary of its ``skills``
    so the text pasted into Copilot Studio tells users (and the orchestrator) what
    the specialist can do. Returns "" when the card is missing or unreadable.
    """
    path = Path(card_path)
    if not path.is_absolute():
        path = _REPO_ROOT / path
    try:
        card = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"  WARN: could not read agent card '{card_path}': {exc}")
        return ""

    description = (card.get("description") or "").strip()
    lines: list[str] = [description] if description else []
    skills = card.get("skills") or []
    if skills:
        lines.append("")
        lines.append("Skills:")
        for skill in skills:
            name = (skill.get("name") or skill.get("id") or "").strip()
            skill_desc = (skill.get("description") or "").strip()
            if name and skill_desc:
                lines.append(f"- {name}: {skill_desc}")
            elif name:
                lines.append(f"- {name}")
    return "\n".join(lines).strip()


def _az(*args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        normalize(["az", *args]), check=False, capture_output=True, text=True
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"az {' '.join(args)} failed ({result.returncode}): "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    return result


def _find_app_id(display_name: str) -> str:
    result = _az(
        "ad", "app", "list", "--display-name", display_name,
        "--query", "[0].appId", "-o", "tsv",
    )
    return result.stdout.strip()


def ensure_app_registration(display_name: str, redirect_uris: list[str]) -> str:
    """Create/reuse the confidential-client app registration; return its appId."""
    app_id = _find_app_id(display_name)
    if not app_id:
        print(f"==> Creating app registration '{display_name}'")
        app_id = _az(
            "ad", "app", "create",
            "--display-name", display_name,
            "--sign-in-audience", "AzureADMyOrg",
            "--web-redirect-uris", *redirect_uris,
            "--query", "appId", "-o", "tsv",
            check=True,
        ).stdout.strip()
    else:
        print(f"==> Reusing app registration '{display_name}' ({app_id})")
        # Ensure the redirect URIs are present (merge, don't clobber existing ones).
        existing = _az(
            "ad", "app", "show", "--id", app_id,
            "--query", "web.redirectUris", "-o", "json",
        ).stdout.strip()
        try:
            current = set(json.loads(existing or "[]"))
        except json.JSONDecodeError:
            current = set()
        merged = sorted(current | set(redirect_uris))
        if current != set(merged):
            print(f"  Updating web redirect URIs: {merged}")
            _az("ad", "app", "update", "--id", app_id,
                "--web-redirect-uris", *merged, check=False)

    # Ensure a service principal exists so we can assign RBAC roles to the app.
    _az("ad", "sp", "create", "--id", app_id)
    return app_id


def add_azure_ai_delegated_permission(app_id: str) -> None:
    """Add + admin-consent the ``user_impersonation`` delegated permission on Azure AI."""
    scope_id = _az(
        "ad", "sp", "show", "--id", AZURE_AI_RESOURCE_APP_ID,
        "--query", "oauth2PermissionScopes[?value=='user_impersonation'].id | [0]",
        "-o", "tsv",
    ).stdout.strip()
    if not scope_id:
        print(
            "  WARN: could not resolve the 'user_impersonation' scope id on "
            f"{AZURE_AI_AUDIENCE}; skipping delegated-permission wiring."
        )
        return

    print(f"==> Adding delegated '{AZURE_AI_AUDIENCE}/user_impersonation' permission")
    _az(
        "ad", "app", "permission", "add", "--id", app_id,
        "--api", AZURE_AI_RESOURCE_APP_ID,
        "--api-permissions", f"{scope_id}=Scope",
    )
    # Grant tenant-wide admin consent so no per-user consent prompt is needed.
    consent = _az("ad", "app", "permission", "admin-consent", "--id", app_id)
    if consent.returncode == 0:
        print("  Granted admin consent for the delegated permission.")
    else:
        print(
            "  WARN: could not grant admin consent automatically "
            f"({(consent.stderr or consent.stdout).strip()}). Grant it in the portal: "
            "Entra ID > App registrations > API permissions > Grant admin consent."
        )


def create_client_secret(app_id: str, years: int, secret_name: str) -> str:
    """Mint (append) a client secret and return its value (shown once)."""
    print(f"==> Creating client secret '{secret_name}' (valid {years} year(s))")
    secret = _az(
        "ad", "app", "credential", "reset", "--id", app_id,
        "--append", "--display-name", secret_name,
        "--years", str(years),
        "--query", "password", "-o", "tsv",
        check=True,
    ).stdout.strip()
    return secret


def resolve_project_id() -> str:
    """Resolve the ARM resource id of the Foundry project (env, else derived)."""
    project_id = os.getenv("AZURE_AI_PROJECT_ID", "").strip()
    if project_id:
        return project_id
    subscription = os.getenv("AZURE_SUBSCRIPTION_ID", "").strip()
    resource_group = os.getenv("AZURE_RESOURCE_GROUP", "").strip()
    project_name = os.getenv("AZURE_AI_PROJECT_NAME", "").strip()
    endpoint = os.getenv("AZURE_AI_PROJECT_ENDPOINT", "").strip()
    account = endpoint.split("://", 1)[1].split(".", 1)[0] if "://" in endpoint else ""
    if subscription and resource_group and account and project_name:
        return (
            f"/subscriptions/{subscription}/resourceGroups/{resource_group}"
            f"/providers/Microsoft.CognitiveServices/accounts/{account}"
            f"/projects/{project_name}"
        )
    return ""


def _sp_object_id(app_id: str) -> str:
    return _az("ad", "sp", "show", "--id", app_id,
               "--query", "id", "-o", "tsv").stdout.strip()


def _signed_in_user_object_id() -> str:
    return _az("ad", "signed-in-user", "show",
               "--query", "id", "-o", "tsv").stdout.strip()


def _resolve_agent_identity_object_id(identifier: str) -> str:
    """Resolve a Copilot Studio agent identity to its service-principal object id.

    ``identifier`` may be the agent identity's object id, application (client) id
    or display name. Returns "" when nothing matches.
    """
    identifier = identifier.strip()
    if not identifier:
        return ""
    # `az ad sp show --id` accepts an object id, appId or identifier URI.
    obj_id = _az("ad", "sp", "show", "--id", identifier,
                 "--query", "id", "-o", "tsv").stdout.strip()
    if obj_id:
        return obj_id
    # Fall back to a display-name lookup.
    return _az("ad", "sp", "list", "--display-name", identifier,
               "--query", "[0].id", "-o", "tsv").stdout.strip()


def _assign_role(principal_object_id: str, principal_type: str, scope: str) -> None:
    """Assign the caller role to a principal, using the correct principal type.

    ``principal_type`` is ``User`` or ``ServicePrincipal`` (or "" to let the CLI
    resolve it via Graph). Idempotent — "already exists" is treated as success.
    """
    args = [
        "role", "assignment", "create",
        "--assignee-object-id", principal_object_id,
        "--role", A2A_CALLER_ROLE,
        "--scope", scope,
    ]
    if principal_type:
        args += ["--assignee-principal-type", principal_type]
    result = _az(*args)
    combined = f"{result.stdout}\n{result.stderr}".lower()
    if result.returncode == 0:
        print(f"    Granted '{A2A_CALLER_ROLE}'.")
    elif "already exists" in combined or "roleassignmentexists" in combined:
        print(f"    '{A2A_CALLER_ROLE}' already assigned (skipped).")
    else:
        print(f"    WARN: could not assign '{A2A_CALLER_ROLE}': "
              f"{(result.stderr or result.stdout).strip()}")


def grant_a2a_caller_role(
    app_id: str,
    extra_object_ids: list[str],
    agent_identity_ids: list[str],
) -> list[str]:
    """Grant the Foundry Agent Consumer role on the project to the relevant principals.

    Returns the resolved object ids of the Copilot Studio agent identities that were
    granted (for the summary banner).
    """
    project_id = resolve_project_id()
    if not project_id:
        print(
            "\nWARN: could not resolve the Foundry project resource id — skipping the "
            f"'{A2A_CALLER_ROLE}' grant. Set AZURE_AI_PROJECT_ID in ./.env and re-run.",
            file=sys.stderr,
        )
        return []

    # (object id) -> (label, principal type). The signed-in user is a *User* — the
    # identity behind Copilot Studio's interactive auth-code flow — while the app's
    # own service principal covers the app-only/client-credentials test.
    principals: dict[str, tuple[str, str]] = {}
    if app_id:
        sp_object_id = _sp_object_id(app_id)
        if sp_object_id:
            principals[sp_object_id] = (
                "app service principal (client-credentials / test)", "ServicePrincipal"
            )
        user_object_id = _signed_in_user_object_id()
        if user_object_id:
            principals.setdefault(
                user_object_id, ("signed-in user (interactive auth-code flow)", "User")
            )

    # Copilot Studio agent identities (agentic auth, no secret) are service
    # principals — resolve each supplied identifier to its object id.
    granted_agent_ids: list[str] = []
    for identifier in agent_identity_ids:
        obj_id = _resolve_agent_identity_object_id(identifier)
        if not obj_id:
            print(
                f"  WARN: could not resolve an agent identity for '{identifier}'. "
                "Pass its object id, application (client) id or display name.",
                file=sys.stderr,
            )
            continue
        if obj_id != identifier:
            print(f"  Resolved agent identity '{identifier}' → {obj_id}")
        principals.setdefault(
            obj_id, ("Copilot Studio agent identity (agentic auth)", "ServicePrincipal")
        )
        granted_agent_ids.append(obj_id)

    for obj_id in extra_object_ids:
        # Type unknown for supplied ids — let the CLI resolve it via Graph.
        principals.setdefault(obj_id, ("extra principal (--grant-object-id)", ""))

    if not principals:
        print(
            f"\nWARN: no principals resolved for the '{A2A_CALLER_ROLE}' grant.",
            file=sys.stderr,
        )
        return granted_agent_ids

    print(f"\n==> Granting '{A2A_CALLER_ROLE}' on the project ({project_id})")
    for obj_id, (label, principal_type) in principals.items():
        print(f"  {label}: {obj_id}")
        _assign_role(obj_id, principal_type, project_id)
    return granted_agent_ids


def _print_parameters(
    *,
    tenant_id: str,
    oauth_enabled: bool,
    client_id: str,
    client_secret: str,
    scopes: str,
    redirect_uri: str,
    specialist_a2a: str,
    agent_description: str,
    agent_identity_ids: list[str],
) -> None:
    line = "=" * 78
    if oauth_enabled:
        authority = f"https://login.microsoftonline.com/{tenant_id}"
        print(f"\n{line}")
        print("Copilot Studio — OAuth 2.0 connection parameters (copy into Copilot Studio)")
        print(line)
        print(f"Client ID*            {client_id}")
        print(f"Client secret*        {client_secret}")
        print(f"Authorization URL*    {authority}/oauth2/v2.0/authorize")
        print(f"Token URL template*   {authority}/oauth2/v2.0/token")
        print(f"Refresh URL*          {authority}/oauth2/v2.0/token")
        print(f"Scopes                {scopes}")
        print(f"Redirect URL          {redirect_uri}")
        print(line)

    if agent_identity_ids:
        print(f"\n{line}")
        print("Copilot Studio — Entra Agent Identity auth (agentic, no secret)")
        print(line)
        print("Configure the Copilot Studio agent to authenticate with its own Entra")
        print("Agent Identity. Token audience: https://ai.azure.com — no client secret")
        print("is required.")
        print(f"Granted '{A2A_CALLER_ROLE}' to agent identity object id(s):")
        for obj_id in agent_identity_ids:
            print(f"  - {obj_id}")
        print(line)

    print(f"\n{line}")
    print(f"Specialist A2A endpoint   {specialist_a2a}")
    print(f"Agent card (v1.0)         {specialist_a2a}/agentCard/v1.0")
    print(line)
    if agent_description:
        print("Agent description (copy into the Copilot Studio agent/tool description)")
        print(line)
        print(agent_description)
        print(line)

    if oauth_enabled:
        print(
            "\nNOTE: the client secret is shown ONCE — store it in a secure place now.\n"
            "RBAC role assignments can take 2-5 minutes to propagate before the first\n"
            "A2A call from Copilot Studio succeeds. Verify the auth flow with:\n"
            f"  python -m scripts.test_copilot_studio_a2a_auth --client-id {client_id} \\\n"
            "      --client-secret <the-secret-above>"
        )
    else:
        print(
            "\nNOTE: RBAC role assignments can take 2-5 minutes to propagate before the\n"
            "first A2A call from the Copilot Studio agent identity succeeds."
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    specialist_default = os.getenv(
        "AZURE_AI_SPECIALIST_AGENT_NAME", "marketing-specialist-agent"
    )
    parser.add_argument(
        "--app-name",
        default=os.getenv("COPILOT_STUDIO_A2A_APP_NAME", f"{specialist_default}-copilot-studio-a2a"),
        help="App-registration display name.",
    )
    parser.add_argument(
        "--redirect-uri", dest="redirect_uris", action="append", default=[],
        help="Redirect URI to register (repeatable). Defaults to the Copilot Studio URI.",
    )
    parser.add_argument(
        "--secret-years", type=int, default=2,
        help="Client-secret validity in years (default: 2).",
    )
    parser.add_argument(
        "--grant-object-id", dest="grant_object_ids", action="append", default=[],
        metavar="OBJECT_ID",
        help="Additional principal object id to grant the Foundry Agent Consumer role (repeatable).",
    )
    parser.add_argument(
        "--scopes",
        default=os.getenv(
            "COPILOT_STUDIO_A2A_SCOPES",
            f"{AZURE_AI_AUDIENCE}/user_impersonation offline_access",
        ),
        help="Scopes string to hand to Copilot Studio.",
    )
    parser.add_argument(
        "--agent-card",
        default=os.getenv("COPILOT_STUDIO_A2A_AGENT_CARD", DEFAULT_AGENT_CARD_PATH),
        help="Path to the specialist's agentcard.json used to build the Copilot "
             "Studio agent description.",
    )
    parser.add_argument(
        "--agent-identity-id", dest="agent_identity_ids", action="append", default=[],
        metavar="AGENT_ID",
        help="Entra Agent Identity of a Copilot Studio agent (app id, object id or "
             "display name) to grant the Foundry Agent Consumer role — enables "
             "agentic auth with no secret (repeatable).",
    )
    parser.add_argument(
        "--agent-identity-only", action="store_true",
        help="Only grant the role to the supplied agent identities; skip the OAuth "
             "app-registration/secret provisioning.",
    )
    args = parser.parse_args(argv)

    env_agent_ids = [
        i.strip()
        for i in os.getenv("COPILOT_STUDIO_AGENT_IDS", "").split(",")
        if i.strip()
    ]
    agent_identity_ids = [*args.agent_identity_ids, *env_agent_ids]

    if args.agent_identity_only and not agent_identity_ids:
        print(
            "ERROR: --agent-identity-only requires at least one --agent-identity-id "
            "(or COPILOT_STUDIO_AGENT_IDS).",
            file=sys.stderr,
        )
        return 1

    oauth_enabled = not args.agent_identity_only

    project_endpoint = os.getenv("AZURE_AI_PROJECT_ENDPOINT", "").strip()
    if not project_endpoint:
        print("ERROR: AZURE_AI_PROJECT_ENDPOINT is required (set it in ./.env).",
              file=sys.stderr)
        return 1

    redirect_uris = args.redirect_uris or [
        os.getenv("COPILOT_STUDIO_REDIRECT_URI", DEFAULT_COPILOT_STUDIO_REDIRECT_URI)
    ]

    tenant_id = resolve_tenant_id()
    specialist_name = specialist_default
    specialist_a2a = a2a_base_url(project_endpoint, specialist_name)

    print(f"==> Tenant:      {tenant_id}")
    print(f"==> Specialist:  {specialist_name}")
    if oauth_enabled:
        print(f"==> Redirect:    {', '.join(redirect_uris)}")
    if agent_identity_ids:
        print(f"==> Agent ids:   {', '.join(agent_identity_ids)}")
    print()

    app_id = ""
    client_secret = ""
    if oauth_enabled:
        try:
            app_id = ensure_app_registration(args.app_name, redirect_uris)
            add_azure_ai_delegated_permission(app_id)
            client_secret = create_client_secret(
                app_id, args.secret_years, f"{args.app_name}-secret"
            )
        except RuntimeError as exc:
            print(f"\nERROR: {exc}", file=sys.stderr)
            return 1

    granted_agent_ids = grant_a2a_caller_role(
        app_id, args.grant_object_ids, agent_identity_ids
    )

    agent_description = build_agent_description(args.agent_card)

    _print_parameters(
        tenant_id=tenant_id,
        oauth_enabled=oauth_enabled,
        client_id=app_id,
        client_secret=client_secret,
        scopes=args.scopes,
        redirect_uri=redirect_uris[0],
        specialist_a2a=specialist_a2a,
        agent_description=agent_description,
        agent_identity_ids=granted_agent_ids,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
