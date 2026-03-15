"""Zoho Mail free inbox provisioning helpers for cold email.

Zoho Mail offers a free tier that lets you host email on **one custom domain**
with up to **5 mailboxes**.  This makes it ideal for cold outreach: you get
professional ``you@yourdomain.com`` addresses at zero cost.

This module helps you:

1. Generate the DNS records (MX, SPF, DKIM, DMARC) required to connect your
   domain to Zoho Mail.
2. Suggest professional email addresses for a given domain.
3. Track which inboxes have been created and produce ready-to-use config
   dicts for Instantly's ``AccountManager.add_inbox()``.
4. Persist everything to a JSON registry file.

Manual steps the user must complete:
    * Sign up at https://mail.zoho.com/signup (free plan).
    * Add your domain and verify ownership via a TXT record.
    * Create up to 5 user mailboxes in the Zoho admin panel.
    * Add the DNS records this tool generates at your domain registrar.

Typical workflow:
    >>> prov = ZohoInboxProvisioner("zoho_registry.json", domain="acme.co")
    >>> prov.print_dns_config()
    >>> emails = prov.generate_emails(["alex", "jordan", "taylor"])
    >>> prov.save()
    >>> # User creates accounts in Zoho admin, adds DNS records ...
    >>> prov.mark_verified("alex@acme.co", password="...")
    >>> configs = prov.get_instantly_configs()
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Zoho Mail connection details (free tier, global DC)
# ---------------------------------------------------------------------------

ZOHO_SMTP = {
    "host": "smtp.zoho.com",
    "port": 587,
}

ZOHO_IMAP = {
    "host": "imap.zoho.com",
    "port": 993,
}

# Zoho MX records for custom domains
ZOHO_MX_RECORDS = [
    {"priority": 10, "host": "mx.zoho.com"},
    {"priority": 20, "host": "mx2.zoho.com"},
    {"priority": 50, "host": "mx3.zoho.com"},
]


class ZohoInboxProvisioner:
    """Generate, track, and configure Zoho Mail free-tier inboxes.

    Zoho's free plan supports 1 custom domain with up to 5 users, which is
    perfect for bootstrapping cold-email sending accounts with a professional
    domain at no cost.

    Args:
        registry_path: Path to the JSON registry file.
        domain: The custom domain hosted on Zoho (e.g. ``"acme.co"``).
        default_daily_limit: Instantly daily sending limit per inbox.
        default_warmup: Enable warmup when adding to Instantly.
    """

    MAX_FREE_USERS = 5

    def __init__(
        self,
        registry_path: str | Path = "zoho_inbox_registry.json",
        domain: str = "",
        default_daily_limit: int = 30,
        default_warmup: bool = True,
    ) -> None:
        self.registry_path = Path(registry_path)
        self.domain = domain.lower().strip()
        self.default_daily_limit = default_daily_limit
        self.default_warmup = default_warmup
        self.inboxes: list[dict[str, Any]] = []
        if self.registry_path.exists():
            self.load()

    # ------------------------------------------------------------------
    # DNS record generation
    # ------------------------------------------------------------------

    def generate_dns_records(self, dkim_selector: str = "zoho") -> list[dict[str, str]]:
        """Generate all DNS records needed to use Zoho Mail with a custom domain.

        Returns a list of record dicts with keys ``type``, ``name``,
        ``value``, and (for MX) ``priority``.

        Args:
            dkim_selector: The DKIM selector configured in Zoho admin.
                Defaults to ``"zoho"``.  The actual DKIM public key must be
                copied from the Zoho admin console.

        Returns:
            List of DNS record dicts.
        """
        if not self.domain:
            raise ValueError("Set the 'domain' attribute before generating DNS records.")

        records: list[dict[str, str]] = []

        # MX records
        for mx in ZOHO_MX_RECORDS:
            records.append({
                "type": "MX",
                "name": self.domain,
                "value": mx["host"],
                "priority": str(mx["priority"]),
            })

        # SPF record
        records.append({
            "type": "TXT",
            "name": self.domain,
            "value": "v=spf1 include:zoho.com ~all",
        })

        # DKIM record (placeholder -- actual key from Zoho admin)
        records.append({
            "type": "TXT",
            "name": f"{dkim_selector}._domainkey.{self.domain}",
            "value": (
                "v=DKIM1; k=rsa; p=<PASTE_YOUR_ZOHO_DKIM_PUBLIC_KEY_HERE>"
            ),
        })

        # DMARC record
        records.append({
            "type": "TXT",
            "name": f"_dmarc.{self.domain}",
            "value": (
                "v=DMARC1; p=none; rua=mailto:dmarc-reports@{domain}; "
                "ruf=mailto:dmarc-reports@{domain}; sp=none; aspf=r;"
            ).format(domain=self.domain),
        })

        return records

    def print_dns_config(self, dkim_selector: str = "zoho") -> None:
        """Print a human-readable DNS setup checklist to stdout.

        Args:
            dkim_selector: DKIM selector string (default ``"zoho"``).
        """
        records = self.generate_dns_records(dkim_selector=dkim_selector)
        print(f"\n{'='*60}")
        print(f"  Zoho Mail DNS Configuration for {self.domain}")
        print(f"{'='*60}\n")
        print("Add the following records at your domain registrar:\n")
        for i, rec in enumerate(records, 1):
            priority_str = f"  Priority : {rec['priority']}" if "priority" in rec else ""
            print(f"  {i}. {rec['type']} Record")
            print(f"     Name     : {rec['name']}")
            print(f"     Value    : {rec['value']}")
            if priority_str:
                print(f"    {priority_str}")
            print()
        print(
            "NOTE: Copy the actual DKIM public key from Zoho Admin > "
            "Email Authentication > DKIM and replace the placeholder above.\n"
        )

    # ------------------------------------------------------------------
    # Email address generation
    # ------------------------------------------------------------------

    def generate_emails(
        self,
        local_parts: list[str] | None = None,
        first_last_pairs: list[tuple[str, str]] | None = None,
    ) -> list[str]:
        """Generate professional email addresses for the configured domain.

        Provide either explicit local parts (``["alex", "info"]``) or
        first/last name pairs to auto-generate them.

        Args:
            local_parts: Explicit local-part strings.
            first_last_pairs: ``(first, last)`` tuples -- generates
                ``first.last``, ``first``, ``flast`` variations.

        Returns:
            List of generated email addresses.

        Raises:
            ValueError: If domain is not set or the free-tier cap is exceeded.
        """
        if not self.domain:
            raise ValueError("Set the 'domain' attribute before generating emails.")

        parts: list[str] = []
        if local_parts:
            parts.extend([p.lower().strip() for p in local_parts])
        if first_last_pairs:
            for first, last in first_last_pairs:
                f, l_ = first.lower().strip(), last.lower().strip()
                parts.extend([f"{f}.{l_}", f, f"{f[0]}{l_}"])

        # De-duplicate while preserving order
        seen: set[str] = set()
        unique: list[str] = []
        for p in parts:
            if p not in seen:
                seen.add(p)
                unique.append(p)

        existing_emails = {e["email"] for e in self.inboxes}
        emails: list[str] = []
        for part in unique:
            addr = f"{part}@{self.domain}"
            if addr in existing_emails:
                continue
            emails.append(addr)
            # Derive display first name from local part
            first_name = part.split(".")[0].title() if "." in part else part.title()
            self.inboxes.append({
                "email": addr,
                "first_name": first_name,
                "domain": self.domain,
                "provider": "zoho",
                "status": "pending",
                "password": None,
                "created_at": None,
                "verified_at": None,
                "added_at": None,
            })

        total = len(self.inboxes)
        if total > self.MAX_FREE_USERS:
            print(
                f"WARNING: You have {total} inboxes registered but Zoho's "
                f"free plan only supports {self.MAX_FREE_USERS} users. "
                f"Extra accounts will require a paid plan."
            )

        return emails

    # ------------------------------------------------------------------
    # SMTP / IMAP helpers
    # ------------------------------------------------------------------

    @staticmethod
    def get_smtp_settings() -> dict[str, Any]:
        """Return Zoho SMTP connection settings."""
        return dict(ZOHO_SMTP)

    @staticmethod
    def get_imap_settings() -> dict[str, Any]:
        """Return Zoho IMAP connection settings."""
        return dict(ZOHO_IMAP)

    @staticmethod
    def get_connection_details() -> dict[str, Any]:
        """Return full SMTP + IMAP connection info for Zoho Mail."""
        return {
            "smtp": dict(ZOHO_SMTP),
            "imap": dict(ZOHO_IMAP),
            "notes": (
                "Use the full email address as both SMTP and IMAP username. "
                "Zoho requires TLS on port 587 for SMTP and SSL on port 993 "
                "for IMAP.  Generate an App Password in Zoho if 2FA is enabled."
            ),
        }

    # ------------------------------------------------------------------
    # Instantly config generation
    # ------------------------------------------------------------------

    def get_instantly_config(self, email: str) -> dict[str, Any]:
        """Build an Instantly ``AccountManager.add_inbox()`` config dict.

        Args:
            email: A verified Zoho email in the registry.

        Returns:
            Dict suitable for ``AccountManager.add_inbox(**config)``.

        Raises:
            ValueError: If not found or missing password.
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
            "provider": "zoho",
            "daily_limit": self.default_daily_limit,
            "warmup": self.default_warmup,
        }

    def get_instantly_configs(self) -> list[dict[str, Any]]:
        """Return Instantly configs for all verified-but-not-added inboxes."""
        return [
            {
                "email": e["email"],
                "password": e["password"],
                "first_name": e["first_name"],
                "provider": "zoho",
                "daily_limit": self.default_daily_limit,
                "warmup": self.default_warmup,
            }
            for e in self.inboxes
            if e["status"] == "verified" and e.get("password")
        ]

    # ------------------------------------------------------------------
    # Status tracking
    # ------------------------------------------------------------------

    def mark_verified(self, email: str, password: str) -> None:
        """Mark an inbox as created in Zoho and record its password."""
        entry = self._find(email)
        if entry is None:
            raise ValueError(f"{email} is not in the registry.")
        entry["password"] = password
        entry["status"] = "verified"
        entry["verified_at"] = datetime.now(timezone.utc).isoformat()
        self.save()

    def mark_added_to_instantly(self, email: str) -> None:
        """Mark an inbox as successfully pushed to Instantly."""
        entry = self._find(email)
        if entry is None:
            raise ValueError(f"{email} is not in the registry.")
        entry["status"] = "added_to_instantly"
        entry["added_at"] = datetime.now(timezone.utc).isoformat()
        self.save()

    def get_pending(self) -> list[dict[str, Any]]:
        """Return inboxes that still need to be created in Zoho."""
        return [e for e in self.inboxes if e["status"] == "pending"]

    def get_verified(self) -> list[dict[str, Any]]:
        """Return inboxes verified but not yet added to Instantly."""
        return [e for e in self.inboxes if e["status"] == "verified"]

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self) -> None:
        """Persist the inbox registry to the JSON file."""
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "domain": self.domain,
            "inboxes": self.inboxes,
        }
        with open(self.registry_path, "w") as fh:
            json.dump(data, fh, indent=2)

    def load(self) -> None:
        """Load the inbox registry from the JSON file."""
        with open(self.registry_path) as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            self.domain = data.get("domain", self.domain)
            self.inboxes = data.get("inboxes", [])
        else:
            # Backwards compat: plain list
            self.inboxes = data

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _find(self, email: str) -> dict[str, Any] | None:
        for entry in self.inboxes:
            if entry["email"].lower() == email.lower():
                return entry
        return None

    def __repr__(self) -> str:
        total = len(self.inboxes)
        pending = len(self.get_pending())
        verified = len(self.get_verified())
        return (
            f"<ZohoInboxProvisioner domain={self.domain!r} "
            f"total={total} pending={pending} verified={verified}>"
        )
