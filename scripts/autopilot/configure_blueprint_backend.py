"""Configure the blueprint backend in the Teams Developer Portal.

Python port of ``configure-blueprint-backend.ps1``. PUTs a bot-based backend
configuration for the agent blueprint so it is wired to the bot (whose bot id is
the same as the blueprint id). This is optional and disabled by default in the
wrapper (matching the upstream sample, which keeps this step commented out).

.. warning::
   The Teams Developer Portal ``agentblueprints/.../backendConfiguration`` API
   **rejects tokens minted for the Azure CLI first-party client**
   (``04b07795-8ddb-461a-bbee-02f9e1bf7b46``) with **HTTP 403**, even when the
   caller is an owner of the blueprint. ``az account get-access-token`` (which
   this script and ``az login --scope ...`` both use) produces exactly such a
   token, so this script will usually 403.

   The **supported path is the Teams Developer Portal UI**: open
   ``https://dev.teams.microsoft.com/tools/agent-blueprint/<blueprint-id>`` →
   **Configuration** → set **Bot ID** = the blueprint id → **Save**. The UI
   uses the portal's own (authorized) client, so it works where the CLI does
   not.

Run standalone (requires AGENT_IDENTITY_BLUEPRINT_ID):

    AGENT_IDENTITY_BLUEPRINT_ID=<id> \
        python -m scripts.autopilot.configure_blueprint_backend
"""

from __future__ import annotations

import os

import requests

from .common import TEAMS_DEV_RESOURCE, get_access_token


def configure_blueprint_backend(blueprint_id: str) -> None:
    """Configure the bot-based backend for the agent blueprint."""
    if not blueprint_id:
        raise ValueError("blueprint_id is required.")

    token = get_access_token(TEAMS_DEV_RESOURCE)
    url = (
        f"https://dev.teams.microsoft.com/api/v1.0/agentblueprints/"
        f"{blueprint_id}/backendConfiguration"
    )
    # Bot id is the same as the agent blueprint id (see the sample readme Step 4).
    body = {"type": "botBased", "botBased": {"botId": blueprint_id}}
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
    }

    print(f"==> PUT {url}")
    response = requests.put(url, headers=headers, json=body, timeout=60)
    response.raise_for_status()
    print(f"==> Blueprint backend configuration completed for blueprint {blueprint_id}.")


def main() -> int:
    blueprint_id = os.getenv("AGENT_IDENTITY_BLUEPRINT_ID", "").strip()
    if not blueprint_id:
        print("❌ AGENT_IDENTITY_BLUEPRINT_ID is required.")
        return 1
    try:
        configure_blueprint_backend(blueprint_id)
    except requests.HTTPError as ex:
        status = ex.response.status_code if ex.response is not None else None
        print(
            "❌ Configure backend failed "
            f"({ex} — {ex.response.text if ex.response else ''})."
        )
        if status == 403:
            print(
                "   HTTP 403: the Teams Developer Portal rejects tokens minted for "
                "the Azure CLI client, even for blueprint owners. Configure the "
                "backend in the UI instead:\n"
                "   https://dev.teams.microsoft.com/tools/agent-blueprint/"
                f"{blueprint_id}\n"
                "   → Configuration → set Bot ID = the blueprint id → Save."
            )
        return 1
    except Exception as ex:  # noqa: BLE001
        print(f"❌ Configure backend failed: {ex}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
