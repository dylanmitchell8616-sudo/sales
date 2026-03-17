#!/usr/bin/env python3
"""Set up Instantly webhooks for real-time reply notifications.

Replaces polling with push-based notifications by registering webhook
subscriptions via the Instantly API V2.

Usage:
    # List all available webhook event types
    python webhooks/setup_webhooks.py --list-events

    # Create webhooks for reply + open events
    python webhooks/setup_webhooks.py --create --url https://your-server.com/webhook

    # List currently registered webhooks
    python webhooks/setup_webhooks.py --list

    # Delete a webhook by ID
    python webhooks/setup_webhooks.py --delete WEBHOOK_ID

Note:
    For the webhook receiver to work in production, it must be deployed on a
    server with a public URL. Options include:
      - A $5/mo VPS (Hetzner, DigitalOcean, Vultr)
      - Railway, Render, or Fly.io (PaaS)
      - ngrok (for local development/testing only)
"""

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Allow imports from the project root.
sys.path.insert(0, str(Path(__file__).parent.parent))
from instantly.client import InstantlyClient

# Preferred event types to subscribe to, in order of priority.
DESIRED_EVENT_TYPES = ["reply_received", "email_opened"]


def load_client() -> InstantlyClient:
    """Load the Instantly API client from .env credentials."""
    env_path = Path(__file__).parent.parent / ".env"
    load_dotenv(env_path)

    api_key = os.getenv("INSTANTLY_API_KEY")
    if not api_key:
        print("Error: INSTANTLY_API_KEY not found in .env file.")
        sys.exit(1)

    return InstantlyClient(api_key)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def list_event_types(client: InstantlyClient) -> list:
    """Fetch and display available webhook event types from Instantly."""
    print("Fetching available webhook event types...\n")

    try:
        result = client.get("webhooks/event-types")
    except Exception as e:
        print(f"Error fetching event types: {e}")
        return []

    # The response may be a list or a dict with a data/items key.
    if isinstance(result, dict):
        event_types = result.get("data", result.get("items", result.get("event_types", [])))
    elif isinstance(result, list):
        event_types = result
    else:
        event_types = []

    if not event_types:
        print("No event types returned. The API response was:")
        print(json.dumps(result, indent=2))
        return []

    print(f"Available event types ({len(event_types)}):")
    print("-" * 50)
    for et in event_types:
        if isinstance(et, dict):
            name = et.get("name", et.get("type", et.get("event_type", "unknown")))
            desc = et.get("description", "")
            print(f"  - {name}" + (f"  ({desc})" if desc else ""))
        else:
            print(f"  - {et}")
    print()

    return event_types


def list_webhooks(client: InstantlyClient) -> list:
    """List all currently registered webhooks."""
    print("Fetching registered webhooks...\n")

    try:
        result = client.get("webhooks")
    except Exception as e:
        print(f"Error fetching webhooks: {e}")
        return []

    if isinstance(result, dict):
        webhooks = result.get("data", result.get("items", []))
    elif isinstance(result, list):
        webhooks = result
    else:
        webhooks = []

    if not webhooks:
        print("No webhooks currently registered.")
        print("Raw response:", json.dumps(result, indent=2))
        return []

    print(f"Registered webhooks ({len(webhooks)}):")
    print("-" * 60)
    for wh in webhooks:
        wh_id = wh.get("id", "?")
        url = wh.get("url", wh.get("webhook_url", "?"))
        event = wh.get("event_type", wh.get("event", "?"))
        enabled = wh.get("enabled", wh.get("active", "?"))
        print(f"  ID:    {wh_id}")
        print(f"  URL:   {url}")
        print(f"  Event: {event}")
        print(f"  Active: {enabled}")
        print()

    return webhooks


def create_webhooks(client: InstantlyClient, webhook_url: str) -> list:
    """Create webhook subscriptions for reply and open events.

    Args:
        client: Authenticated InstantlyClient.
        webhook_url: The public URL that will receive POST payloads.

    Returns:
        List of created webhook objects.
    """
    print(f"Target webhook URL: {webhook_url}\n")

    # First, discover available event types so we only subscribe to valid ones.
    print("Checking available event types...")
    try:
        result = client.get("webhooks/event-types")
        if isinstance(result, dict):
            raw = result.get("data", result.get("items", result.get("event_types", [])))
        elif isinstance(result, list):
            raw = result
        else:
            raw = []

        available = set()
        for et in raw:
            if isinstance(et, dict):
                available.add(et.get("name", et.get("type", et.get("event_type", ""))))
            else:
                available.add(str(et))
    except Exception:
        # If the event-types endpoint fails, try subscribing anyway.
        print("  Could not fetch event types; will attempt subscription directly.")
        available = set(DESIRED_EVENT_TYPES)

    created = []
    for event_type in DESIRED_EVENT_TYPES:
        if available and event_type not in available:
            print(f"  Skipping '{event_type}' (not available in this Instantly plan).")
            continue

        print(f"  Creating webhook for '{event_type}'...")
        payload = {
            "event_type": event_type,
            "url": webhook_url,
        }

        try:
            resp = client.post("webhooks", json=payload)
            wh_id = resp.get("id", "unknown")
            print(f"    Created webhook {wh_id}")
            created.append(resp)
        except Exception as e:
            print(f"    Failed to create webhook for '{event_type}': {e}")

    print(f"\nDone. Created {len(created)} webhook(s).")
    return created


def delete_webhook(client: InstantlyClient, webhook_id: str) -> None:
    """Delete a webhook subscription by its ID."""
    print(f"Deleting webhook {webhook_id}...")
    try:
        client.delete(f"webhooks/{webhook_id}")
        print("  Deleted successfully.")
    except Exception as e:
        print(f"  Failed to delete webhook: {e}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Manage Instantly webhooks for real-time notifications.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--list-events",
        action="store_true",
        help="List available webhook event types.",
    )
    group.add_argument(
        "--list",
        action="store_true",
        help="List currently registered webhooks.",
    )
    group.add_argument(
        "--create",
        action="store_true",
        help="Create webhooks for reply_received and email_opened events.",
    )
    group.add_argument(
        "--delete",
        metavar="WEBHOOK_ID",
        help="Delete a webhook by its ID.",
    )
    parser.add_argument(
        "--url",
        help="Public URL for the webhook receiver (required with --create).",
    )

    args = parser.parse_args()
    client = load_client()

    if args.list_events:
        list_event_types(client)

    elif args.list:
        list_webhooks(client)

    elif args.create:
        if not args.url:
            parser.error("--create requires --url <public_webhook_url>")
        create_webhooks(client, args.url)

    elif args.delete:
        delete_webhook(client, args.delete)


if __name__ == "__main__":
    main()
