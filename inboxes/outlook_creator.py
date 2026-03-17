"""Outlook/Hotmail free inbox provisioning helpers for cold email.

This module generates professional email address suggestions, tracks inbox
creation status, and auto-configures verified accounts in Instantly.ai.

IMPORTANT: Microsoft actively blocks automated Outlook account creation.
Users must create accounts manually at https://signup.live.com/.  This tool
handles everything *around* the manual step:

  1. Generate a batch of professional-looking email variations.
  2. Save them to a local registry so you can track which ones are created.
  3. Once created, mark them as verified and push their SMTP/IMAP config
     straight into Instantly via the API.

Typical workflow:
    >>> prov = OutlookInboxProvisioner("inboxes/outlook_registry.json")
    >>> suggestions = prov.generate_emails("Jane", "Smith", count=5)
    >>> prov.save()  # persist to disk
    >>> # User goes and creates the accounts manually ...
    >>> prov.mark_verified("jane.smith@outlook.com", password="...")
    >>> configs = prov.get_instantly_configs()
    >>> account_mgr.add_bulk_inboxes(configs)
"""

from __future__ import annotations

import itertools
import json
import random
import string
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Connection details for Outlook / Hotmail / Live
# ---------------------------------------------------------------------------

OUTLOOK_SMTP = {
    "host": "smtp-mail.outlook.com",
    "port": 587,
}

OUTLOOK_IMAP = {
    "host": "outlook.office365.com",
    "port": 993,
}

OUTLOOK_DOMAINS = ["outlook.com", "hotmail.com"]


class OutlookInboxProvisioner:
    """Generate, track, and configure free Outlook/Hotmail inboxes.

    This class does **not** create Outlook accounts automatically -- Microsoft
    requires CAPTCHA and phone verification which cannot be scripted reliably.
    Instead it:

    * Suggests professional email addresses from first/last name patterns.
    * Persists an inbox registry (JSON) so you know which addresses to create.
    * Produces ready-to-use Instantly ``AccountManager.add_inbox()`` configs
      once the accounts exist.

    Args:
        registry_path: Path to a JSON file used to persist the inbox list.
            Created automatically if it does not exist.
        default_daily_limit: Default Instantly daily sending limit per inbox.
        default_warmup: Whether to enable warmup when adding to Instantly.
    """

    def __init__(
        self,
        registry_path: str | Path = "outlook_inbox_registry.json",
        default_daily_limit: int = 30,
        default_warmup: bool = True,
    ) -> None:
        self.registry_path = Path(registry_path)
        self.default_daily_limit = default_daily_limit
        self.default_warmup = default_warmup
        self.inboxes: list[dict[str, Any]] = []
        if self.registry_path.exists():
            self.load()

    # ------------------------------------------------------------------
    # Email address generation
    # ------------------------------------------------------------------

    def generate_emails(
        self,
        first_name: str,
        last_name: str,
        count: int = 5,
        domains: list[str] | None = None,
    ) -> list[str]:
        """Generate professional email address suggestions.

        Produces variations such as:
            firstname.lastname@outlook.com
            firstnamelastname@outlook.com
            f.lastname@outlook.com
            firstname.l@hotmail.com
            firstname.lastname123@outlook.com

        Already-registered addresses are excluded from results.

        Args:
            first_name: User's first name (e.g. "Jane").
            last_name:  User's last name (e.g. "Smith").
            count:      Maximum number of suggestions to return.
            domains:    Domains to use.  Defaults to ``OUTLOOK_DOMAINS``.

        Returns:
            A list of suggested email addresses.
        """
        first = first_name.lower().strip()
        last = last_name.lower().strip()
        domains = domains or list(OUTLOOK_DOMAINS)

        # Build local-part patterns (ordered from most to least professional)
        patterns: list[str] = [
            f"{first}.{last}",
            f"{first}{last}",
            f"{first[0]}.{last}",
            f"{first}.{last[0]}",
            f"{first[0]}{last}",
            f"{last}.{first}",
            f"{last}{first[0]}",
            f"{first}.{last}{random.randint(1, 99)}",
            f"{first}{last}{random.randint(10, 999)}",
            f"{first[0]}{last}{random.randint(1, 99)}",
        ]

        existing = {inbox["email"] for inbox in self.inboxes}
        suggestions: list[str] = []
        for local, domain in itertools.product(patterns, domains):
            addr = f"{local}@{domain}"
            if addr not in existing:
                suggestions.append(addr)
            if len(suggestions) >= count:
                break

        # Register them as pending
        for addr in suggestions:
            fname_display = first_name.strip().title()
            self.inboxes.append({
                "email": addr,
                "first_name": fname_display,
                "last_name": last_name.strip().title(),
                "provider": "outlook",
                "status": "pending",  # pending -> verified -> added_to_instantly
                "password": None,
                "created_at": None,
                "verified_at": None,
                "added_at": None,
            })

        return suggestions

    # ------------------------------------------------------------------
    # SMTP / IMAP helpers
    # ------------------------------------------------------------------

    @staticmethod
    def get_smtp_settings() -> dict[str, Any]:
        """Return Outlook SMTP connection settings."""
        return dict(OUTLOOK_SMTP)

    @staticmethod
    def get_imap_settings() -> dict[str, Any]:
        """Return Outlook IMAP connection settings."""
        return dict(OUTLOOK_IMAP)

    @staticmethod
    def get_connection_details() -> dict[str, Any]:
        """Return full SMTP + IMAP connection info for Outlook."""
        return {
            "smtp": dict(OUTLOOK_SMTP),
            "imap": dict(OUTLOOK_IMAP),
            "notes": (
                "Use the full email address as both SMTP and IMAP username. "
                "Outlook requires TLS on port 587 for SMTP and SSL on port 993 "
                "for IMAP.  If 2FA is enabled on the Microsoft account you must "
                "generate an App Password."
            ),
        }

    # ------------------------------------------------------------------
    # Instantly config generation
    # ------------------------------------------------------------------

    def get_instantly_config(self, email: str) -> dict[str, Any]:
        """Build an Instantly ``AccountManager.add_inbox()`` config dict.

        Args:
            email: The Outlook email address (must be in the registry and
                   marked as verified with a password set).

        Returns:
            A dict ready to be unpacked into ``AccountManager.add_inbox()``.

        Raises:
            ValueError: If the email is not in the registry or has no password.
        """
        entry = self._find(email)
        if entry is None:
            raise ValueError(f"{email} is not in the inbox registry.")
        if not entry.get("password"):
            raise ValueError(
                f"{email} has no password set. Call mark_verified() first."
            )

        return {
            "email": entry["email"],
            "password": entry["password"],
            "first_name": entry["first_name"],
            "provider": "outlook",
            "daily_limit": self.default_daily_limit,
            "warmup": self.default_warmup,
        }

    def get_instantly_configs(self) -> list[dict[str, Any]]:
        """Return Instantly configs for all verified inboxes that haven't
        been added yet."""
        configs: list[dict[str, Any]] = []
        for entry in self.inboxes:
            if entry["status"] == "verified" and entry.get("password"):
                configs.append({
                    "email": entry["email"],
                    "password": entry["password"],
                    "first_name": entry["first_name"],
                    "provider": "outlook",
                    "daily_limit": self.default_daily_limit,
                    "warmup": self.default_warmup,
                })
        return configs

    def generate_batch_configs(
        self,
        name_combos: list[tuple[str, str]],
        count_per_name: int = 3,
        domains: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Generate inbox configs from a list of (first_name, last_name) tuples.

        This combines ``generate_emails`` with ``get_instantly_configs`` for
        batch provisioning.  Note: the returned configs will only be usable
        once the accounts are manually created and ``mark_verified()`` is
        called for each.

        Args:
            name_combos:    List of (first_name, last_name) pairs.
            count_per_name: How many email variants per name combo.
            domains:        Override default Outlook domains.

        Returns:
            List of generated email addresses (as dicts with ``email`` and
            ``first_name`` keys -- passwords will be ``None`` until verified).
        """
        results: list[dict[str, Any]] = []
        for first, last in name_combos:
            emails = self.generate_emails(first, last, count=count_per_name, domains=domains)
            for addr in emails:
                results.append({
                    "email": addr,
                    "first_name": first.strip().title(),
                    "last_name": last.strip().title(),
                    "status": "pending",
                })
        self.save()
        return results

    # ------------------------------------------------------------------
    # Status tracking
    # ------------------------------------------------------------------

    def mark_verified(self, email: str, password: str) -> None:
        """Mark an inbox as manually created and record its password.

        Call this after the user has signed up for the Outlook account.

        Args:
            email:    The email address.
            password: The account password (or app-password if 2FA is on).
        """
        entry = self._find(email)
        if entry is None:
            raise ValueError(f"{email} is not in the registry.")
        entry["password"] = password
        entry["status"] = "verified"
        entry["verified_at"] = datetime.now(timezone.utc).isoformat()
        self.save()

    def mark_added_to_instantly(self, email: str) -> None:
        """Mark an inbox as successfully added to Instantly."""
        entry = self._find(email)
        if entry is None:
            raise ValueError(f"{email} is not in the registry.")
        entry["status"] = "added_to_instantly"
        entry["added_at"] = datetime.now(timezone.utc).isoformat()
        self.save()

    def get_pending(self) -> list[dict[str, Any]]:
        """Return all inboxes that still need to be created manually."""
        return [e for e in self.inboxes if e["status"] == "pending"]

    def get_verified(self) -> list[dict[str, Any]]:
        """Return all inboxes that are verified but not yet in Instantly."""
        return [e for e in self.inboxes if e["status"] == "verified"]

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self) -> None:
        """Persist the inbox registry to the JSON file."""
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.registry_path, "w") as fh:
            json.dump(self.inboxes, fh, indent=2)

    def load(self) -> None:
        """Load the inbox registry from the JSON file."""
        with open(self.registry_path) as fh:
            self.inboxes = json.load(fh)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _find(self, email: str) -> dict[str, Any] | None:
        """Find an inbox entry by email address."""
        for entry in self.inboxes:
            if entry["email"].lower() == email.lower():
                return entry
        return None

    def __repr__(self) -> str:
        total = len(self.inboxes)
        pending = len(self.get_pending())
        verified = len(self.get_verified())
        return (
            f"<OutlookInboxProvisioner "
            f"total={total} pending={pending} verified={verified}>"
        )
