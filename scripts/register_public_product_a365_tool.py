"""Print the a365 CLI command to register the **public product MCP server** as
an Agent 365 bring-your-own (BYO) external MCP tool.

Builds and outputs the ``a365 develop-mcp register-external-mcp-server`` command
from environment variables (and the ``register-external-mcp-server.json``
manifest) so it can be reviewed and run manually, or piped straight to a shell.
This registers the deployed ``public-product-mcp-server`` Container App — the
public, anonymous NorthStar Health product catalogue (no prices, margins or
costs) — as an Agent 365 external MCP tool with **NoAuth**.

See https://learn.microsoft.com/en-us/microsoft-365/admin/manage/manage-tools-for-agent

Usage::

    # Print the command
    python -m scripts.register_public_product_a365_tool

    # Print and execute immediately
    eval $(python -m scripts.register_public_product_a365_tool)

Prerequisites:
  - Agent 365 CLI installed (``a365``), version 1.1.165-preview or greater.
  - The public product MCP server deployed with a publicly reachable ``/mcp`` URL.

Environment variables:
  PUBLIC_PRODUCT_MCP_URL          MCP endpoint URL of the deployed server. If
                                  unset, derived from the
                                  ``public-product-mcp-server`` Container App
                                  FQDN using AZURE_RESOURCE_GROUP.
  PUBLIC_PRODUCT_MCP_APP_NAME     Container App name (default: public-product-mcp-server).
  AZURE_RESOURCE_GROUP            Resource group containing the Container App.
  PUBLIC_PRODUCT_MCP_SERVER_NAME  A365 server identifier — must start with
                                  ``ext_`` and be <= 20 chars (default: ext_public_product).
  PUBLIC_PRODUCT_MCP_PUBLISHER    Publisher name in the tool metadata (default: NorthStar Health).
  PUBLIC_PRODUCT_MCP_DESCRIPTION  Server description in the tool metadata.
  PUBLIC_PRODUCT_MCP_TOOLS        Raw ``--tools`` value to advertise. If unset,
                                  a comma-separated list of tool names is loaded
                                  from register-external-mcp-server.json.
  A365_DRY_RUN                    Set to ``true`` to append ``--dry-run``.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path

from dotenv import load_dotenv

from scripts.deploy_helpers import get_container_app_fqdn

_REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(dotenv_path=_REPO_ROOT / ".env", override=True)
load_dotenv(override=False)

# Agent 365 caps the server (short) description at 80 characters.
_MAX_SERVER_DESCRIPTION = 80

# The committed *template* (serverUrl left blank) and the git-ignored *generated*
# manifest that the scripts fill with the real deployed URL. The generated file
# is what you pass to ``a365 ... -f <file>``; it is never checked in.
_TEMPLATE_PATH = (
    _REPO_ROOT / "src" / "public_product_mcp_server" / "register-external-mcp-server.json"
)
_GENERATED_PATH = (
    _REPO_ROOT
    / "src" / "public_product_mcp_server"
    / "register-external-mcp-server.generated.json"
)


def _load_manifest() -> dict:
    """Load the manifest, preferring the generated file over the template."""
    path = _GENERATED_PATH if _GENERATED_PATH.exists() else _TEMPLATE_PATH
    return json.loads(path.read_text(encoding="utf-8"))


def _persist_server_url(url: str) -> None:
    """Write the generated manifest (from the template) with the real serverUrl.

    Produces the git-ignored ``register-external-mcp-server.generated.json`` so it
    can be used directly via ``a365 ... -f <file>``. The committed template keeps
    ``serverUrl`` blank.
    """
    try:
        manifest = json.loads(_TEMPLATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    manifest["serverUrl"] = url
    _GENERATED_PATH.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"  Wrote {_GENERATED_PATH.name} (serverUrl -> {url})")


def _load_tools() -> str:
    """Return the ``--tools`` value: a comma-separated list of tool names.

    Honours ``PUBLIC_PRODUCT_MCP_TOOLS`` as a verbatim override; otherwise reads
    the tool names from register-external-mcp-server.json (e.g.
    ``list_products,search_products,get_product``).
    """
    override = os.getenv("PUBLIC_PRODUCT_MCP_TOOLS", "").strip()
    if override:
        return override
    manifest = _load_manifest()
    names = [t["name"] for t in manifest.get("tools", []) if t.get("name")]
    return ",".join(names)


def _resolve_mcp_url() -> str:
    url = os.getenv("PUBLIC_PRODUCT_MCP_URL", "").strip()
    if url:
        return url
    resource_group = os.getenv("AZURE_RESOURCE_GROUP", "").strip()
    app_name = os.getenv("PUBLIC_PRODUCT_MCP_APP_NAME", "public-product-mcp-server")
    if resource_group:
        try:
            fqdn = get_container_app_fqdn(resource_group, app_name)
        except (subprocess.CalledProcessError, FileNotFoundError):
            fqdn = ""
        if fqdn:
            return f"https://{fqdn}/mcp"
    return ""


def _server_description(manifest: dict) -> str:
    """Return the server short description, capped at 80 chars (the A365 limit)."""
    description = os.getenv(
        "PUBLIC_PRODUCT_MCP_DESCRIPTION",
        manifest.get(
            "description",
            "Public NorthStar Health product catalogue (no prices/margins/costs).",
        ),
    ).strip()
    if len(description) > _MAX_SERVER_DESCRIPTION:
        print(
            f"  WARN: server description exceeds {_MAX_SERVER_DESCRIPTION} chars "
            f"({len(description)}) — truncating."
        )
        description = description[:_MAX_SERVER_DESCRIPTION].rstrip()
    return description


def build_command(mcp_url: str) -> list[str]:
    manifest = _load_manifest()
    cmd = [
        "a365", "develop-mcp", "register-external-mcp-server",
        "--server-name", os.getenv(
            "PUBLIC_PRODUCT_MCP_SERVER_NAME",
            manifest.get("serverName", "ext_public_product"),
        ).strip(),
        "--server-url", mcp_url,
        "--publisher", os.getenv(
            "PUBLIC_PRODUCT_MCP_PUBLISHER",
            manifest.get("publisherName", "NorthStar Health"),
        ).strip(),
        "--description", _server_description(manifest),
        "--auth-type", "NoAuth",
        "--tools", _load_tools(),
    ]
    if os.getenv("A365_DRY_RUN", "false").strip().lower() == "true":
        cmd.append("--dry-run")
    return cmd


def _shell_quote(s: str) -> str:
    """Shell-quote a value so embedded spaces, quotes and JSON stay intact."""
    return shlex.quote(s)


def deploy() -> None:
    mcp_url = _resolve_mcp_url()
    if not mcp_url:
        print(
            "Error: cannot resolve the public product MCP URL.\n"
            "Set PUBLIC_PRODUCT_MCP_URL, or set AZURE_RESOURCE_GROUP so the URL "
            "can be\nderived from the public-product-mcp-server Container App FQDN."
        )
        return

    # Keep the manifest's serverUrl in sync with the resolved endpoint.
    _persist_server_url(mcp_url)

    cmd = build_command(mcp_url)

    # Render as a readable multi-line shell command.
    # Positional tokens (a365 / sub-commands) go on the first line;
    # each --flag value pair on its own continuation line.
    parts: list[str] = []
    i = 0
    while i < len(cmd):
        token = cmd[i]
        if token.startswith("--") and i + 1 < len(cmd) and not cmd[i + 1].startswith("--"):
            parts.append(f"{token} {_shell_quote(cmd[i + 1])}")
            i += 2
        else:
            parts.append(_shell_quote(token))
            i += 1

    print(" \\\n  ".join(parts))


if __name__ == "__main__":
    deploy()
