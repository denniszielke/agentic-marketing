"""Delete the Entra app registrations created by the Agent 365 external-MCP
registration of the **public product MCP server**.

When ``a365 develop-mcp register-external-mcp-server`` runs, it creates two Entra
app registrations named after the A365 server:

  * ``<server-name>-A365Proxy``      — the tooling-gateway proxy app.
  * ``<server-name>-PublicClients``  — the public-client app.

If the registration fails part-way (e.g. the MCC environment is still
provisioning), the CLI does **not** roll these back and prints:

    Entra app registrations were NOT rolled back. Delete them manually …

This script deletes those two app registrations (by their deterministic display
names) so you can retry cleanly. Best-effort and idempotent — missing apps are
skipped.

Requires: Azure CLI signed in (``az login``) with rights to delete app
registrations.

Usage::

    python -m scripts.delete_public_product_a365_registration
    python -m scripts.delete_public_product_a365_registration --server-name ext_public_product
    python -m scripts.delete_public_product_a365_registration --dry-run

Environment variables:
  PUBLIC_PRODUCT_MCP_SERVER_NAME   A365 server identifier (default: read from the
                                   register-external-mcp-server.json manifest, else
                                   ``ext_public_product``).
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

_MANIFEST_PATH = (
    _REPO_ROOT / "src" / "public_product_mcp_server" / "register-external-mcp-server.json"
)

# Suffixes the a365 CLI appends to the server name when creating the app regs.
_APP_SUFFIXES = ("-A365Proxy", "-PublicClients")


def _az(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(normalize(["az", *args]), check=False, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(
            f"az {' '.join(args)} failed ({result.returncode}): "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    return result


def _resolve_server_name(cli_name: str | None) -> str:
    if cli_name:
        return cli_name
    env_name = os.getenv("PUBLIC_PRODUCT_MCP_SERVER_NAME", "").strip()
    if env_name:
        return env_name
    try:
        manifest = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
        name = (manifest.get("serverName") or "").strip()
        if name:
            return name
    except (OSError, json.JSONDecodeError):
        pass
    return "ext_public_product"


def _find_app_ids(display_name: str) -> list[str]:
    """Return the appIds of every app registration with the given display name."""
    result = _az(
        "ad", "app", "list", "--display-name", display_name,
        "--query", "[].appId", "-o", "json", check=False,
    )
    out = result.stdout.strip()
    if not out:
        return []
    try:
        return [a for a in json.loads(out) if a]
    except json.JSONDecodeError:
        return []


def _delete_app(display_name: str, app_id: str, dry_run: bool) -> bool:
    if dry_run:
        print(f"  [dry-run] would delete '{display_name}' ({app_id})")
        return True
    result = _az("ad", "app", "delete", "--id", app_id, check=False)
    if result.returncode == 0:
        print(f"  deleted '{display_name}' ({app_id})")
        return True
    print(
        f"  ERROR: could not delete '{display_name}' ({app_id}): "
        f"{result.stderr.strip() or result.stdout.strip()}",
        file=sys.stderr,
    )
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--server-name", dest="server_name", default=None,
        help="A365 server name whose app registrations to delete "
        "(default: manifest serverName or ext_public_product).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="List what would be deleted without deleting anything.",
    )
    args = parser.parse_args(argv)

    server_name = _resolve_server_name(args.server_name)
    display_names = [f"{server_name}{suffix}" for suffix in _APP_SUFFIXES]
    print(f"==> Deleting Agent 365 app registrations for server '{server_name}':")
    for name in display_names:
        print(f"    - {name}")

    failures = 0
    found_any = False
    for display_name in display_names:
        app_ids = _find_app_ids(display_name)
        if not app_ids:
            print(f"\n  no app registration '{display_name}' found (skipped)")
            continue
        found_any = True
        print(f"\n  {display_name}:")
        for app_id in app_ids:
            if not _delete_app(display_name, app_id, args.dry_run):
                failures += 1

    if not found_any:
        print("\nNothing to delete — no matching app registrations exist.")
        return 0

    print("\nDone." if not failures else f"\nDone with {failures} failure(s).")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
