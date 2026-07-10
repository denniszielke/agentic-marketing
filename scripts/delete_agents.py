"""Delete the marketing **Foundry hosted agents** and their toolboxes.

Removes the two Foundry hosted agents (market intelligence, executive strategy)
and, optionally, the two Foundry toolboxes (marketing, strategy). Container Apps
(MCP servers + web recommender) are removed separately by
``scripts/delete_container_apps.py``.

Usage::

    python -m scripts.delete_agents                 # delete hosted agents only
    python -m scripts.delete_agents --toolboxes     # also delete the toolboxes

Environment variables:
  AZURE_AI_PROJECT_ENDPOINT       Foundry project endpoint (required).
  AZURE_AI_MARKET_AGENT_NAME      default: market-intelligence-agent
  AZURE_AI_STRATEGY_AGENT_NAME    default: executive-strategy-agent
  AZURE_AI_MEETING_PREP_AGENT_NAME default: marketing-meeting-prep-agent
  MARKETING_TOOLBOX_NAME          default: marketing_toolbox
  STRATEGY_TOOLBOX_NAME           default: strategy_toolbox
  WORKIQ_TOOLBOX_NAME             default: workiq-tools
"""

from __future__ import annotations

import os
import sys

from scripts.agent_deploy_helpers import get_client

AGENT_NAMES = [
    os.getenv("AZURE_AI_MARKET_AGENT_NAME", "market-intelligence-agent"),
    os.getenv("AZURE_AI_STRATEGY_AGENT_NAME", "executive-strategy-agent"),
    os.getenv("AZURE_AI_MEETING_PREP_AGENT_NAME", "marketing-meeting-prep-agent"),
]

TOOLBOX_NAMES = [
    os.getenv("MARKETING_TOOLBOX_NAME", "marketing_toolbox"),
    os.getenv("STRATEGY_TOOLBOX_NAME", "strategy_toolbox"),
    os.getenv("WORKIQ_TOOLBOX_NAME", "workiq-tools"),
]


def _delete_agent(client, name: str) -> None:
    """Best-effort delete of a Foundry hosted agent by name."""
    for attempt in (
        lambda: client.agents.delete(agent_name=name),
        lambda: client.agents.delete_agent(agent_name=name),
    ):
        try:
            attempt()
            print(f"Deleted hosted agent '{name}'.")
            return
        except AttributeError:
            continue
        except Exception as exc:  # pragma: no cover - tolerate not-found / API drift
            print(f"  WARN: could not delete agent '{name}': {exc}")
            return
    print(f"  WARN: no delete method available for agent '{name}'.")


def _delete_toolbox(client, name: str) -> None:
    try:
        client.toolboxes.delete(name=name)
        print(f"Deleted toolbox '{name}'.")
    except Exception as exc:  # pragma: no cover - tolerate not-found
        print(f"  WARN: could not delete toolbox '{name}': {exc}")


def delete_all(delete_toolboxes: bool = False) -> None:
    if not os.getenv("AZURE_AI_PROJECT_ENDPOINT"):
        print("ERROR: AZURE_AI_PROJECT_ENDPOINT must be set.", file=sys.stderr)
        sys.exit(1)

    client = get_client()
    for name in AGENT_NAMES:
        print(f"\n==> Deleting hosted agent '{name}'")
        _delete_agent(client, name)

    if delete_toolboxes:
        for name in TOOLBOX_NAMES:
            print(f"\n==> Deleting toolbox '{name}'")
            _delete_toolbox(client, name)

    print("\nDone.")


if __name__ == "__main__":
    delete_all(delete_toolboxes="--toolboxes" in sys.argv)
