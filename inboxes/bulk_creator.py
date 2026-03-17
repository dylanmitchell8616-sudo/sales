"""Bulk inbox creation orchestrator for cold email.

Coordinates the end-to-end process of provisioning multiple email sending
accounts across different providers (Outlook free, Zoho free, custom domain)
and adding them to Instantly.ai.

Since most free email providers block fully automated account creation, this
module focuses on:

  1. Generating email addresses based on a chosen strategy.
  2. Outputting a step-by-step manual checklist for the user.
  3. Tracking account creation, verification, and Instantly onboarding status.
  4. Auto-adding verified accounts to Instantly via the API.
  5. Exporting the full inbox list to CSV for record-keeping.

Usage:
    >>> from instantly import InstantlyClient, AccountManager
    >>> from inboxes.bulk_creator import BulkInboxCreator
    >>>
    >>> creator = BulkInboxCreator(strategy="outlook_free")
    >>> creator.generate_batch([("Alex", "Chen"), ("Jordan", "Lee")])
    >>> creator.print_checklist()
    >>> # ... user creates accounts manually ...
    >>> creator.mark_created("alex.chen@outlook.com", password="...")
    >>> creator.push_to_instantly(account_mgr)
    >>> creator.export_csv("inboxes.csv")
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .outlook_creator import OutlookInboxProvisioner
from .zoho_creator import ZohoInboxProvisioner


# Allowed strategy names
STRATEGIES = ("outlook_free", "zoho_free", "custom_domain")


class BulkInboxCreator:
    """Orchestrate bulk email inbox provisioning across providers.

    Args:
        strategy: One of ``"outlook_free"``, ``"zoho_free"``, or
            ``"custom_domain"``.
        registry_path: Path to persist the master inbox registry JSON.
        domain: Required for ``"zoho_free"`` and ``"custom_domain"``
            strategies.  The custom domain to use for email addresses.
        daily_limit: Default Instantly daily sending limit per inbox.
        warmup: Enable warmup when adding inboxes to Instantly.
    """

    def __init__(
        self,
        strategy: str = "outlook_free",
        registry_path: str | Path = "bulk_inbox_registry.json",
        domain: str = "",
        daily_limit: int = 30,
        warmup: bool = True,
    ) -> None:
        if strategy not in STRATEGIES:
            raise ValueError(
                f"Unknown strategy {strategy!r}. Choose from: {STRATEGIES}"
            )
        self.strategy = strategy
        self.registry_path = Path(registry_path)
        self.domain = domain.lower().strip()
        self.daily_limit = daily_limit
        self.warmup = warmup

        # Master list of all inboxes across providers
        self.inboxes: list[dict[str, Any]] = []
        if self.registry_path.exists():
            self.load()

        # Lazily initialised provider helpers
        self._outlook: OutlookInboxProvisioner | None = None
        self._zoho: ZohoInboxProvisioner | None = None

    # ------------------------------------------------------------------
    # Provider accessors
    # ------------------------------------------------------------------

    @property
    def outlook(self) -> OutlookInboxProvisioner:
        """Outlook provisioner (created on first access)."""
        if self._outlook is None:
            self._outlook = OutlookInboxProvisioner(
                registry_path=self.registry_path.parent / "outlook_registry.json",
                default_daily_limit=self.daily_limit,
                default_warmup=self.warmup,
            )
        return self._outlook

    @property
    def zoho(self) -> ZohoInboxProvisioner:
        """Zoho provisioner (created on first access)."""
        if self._zoho is None:
            self._zoho = ZohoInboxProvisioner(
                registry_path=self.registry_path.parent / "zoho_registry.json",
                domain=self.domain,
                default_daily_limit=self.daily_limit,
                default_warmup=self.warmup,
            )
        return self._zoho

    # ------------------------------------------------------------------
    # Batch generation
    # ------------------------------------------------------------------

    def generate_batch(
        self,
        name_combos: list[tuple[str, str]],
        count_per_name: int = 3,
    ) -> list[str]:
        """Generate a batch of email addresses based on the current strategy.

        Args:
            name_combos: List of ``(first_name, last_name)`` tuples.
            count_per_name: Number of email variants per name combo.

        Returns:
            List of generated email addresses.
        """
        generated: list[str] = []

        if self.strategy == "outlook_free":
            for first, last in name_combos:
                emails = self.outlook.generate_emails(
                    first, last, count=count_per_name,
                )
                generated.extend(emails)

        elif self.strategy in ("zoho_free", "custom_domain"):
            if not self.domain:
                raise ValueError(
                    f"A domain is required for strategy {self.strategy!r}. "
                    "Pass domain= to the constructor."
                )
            self.zoho.domain = self.domain
            emails = self.zoho.generate_emails(
                first_last_pairs=name_combos,
            )
            generated.extend(emails)

        # Mirror into master registry
        for addr in generated:
            if not self._find(addr):
                first_name = addr.split("@")[0].split(".")[0].title()
                self.inboxes.append({
                    "email": addr,
                    "first_name": first_name,
                    "strategy": self.strategy,
                    "status": "pending",
                    "password": None,
                    "created_at": None,
                    "verified_at": None,
                    "added_to_instantly_at": None,
                })

        self.save()
        return generated

    # ------------------------------------------------------------------
    # Legacy API compatibility
    # ------------------------------------------------------------------

    def generate_inbox_plan(
        self,
        count: int = 5,
        first_names: list[str] | None = None,
        last_names: list[str] | None = None,
        domain: str | None = None,
    ) -> list[dict]:
        """Generate a plan for creating inboxes based on strategy.

        This is a convenience wrapper that builds name combos from separate
        first/last name lists and delegates to ``generate_batch()``.

        Args:
            count:       Maximum number of inboxes to generate.
            first_names: Pool of first names to draw from.
            last_names:  Pool of last names to draw from.
            domain:      Domain for zoho_free / custom_domain strategies.

        Returns:
            List of inbox spec dicts with suggested emails.
        """
        if first_names is None:
            first_names = [
                "alex", "jordan", "taylor", "morgan", "casey",
                "riley", "avery", "parker", "quinn", "sage",
            ]
        if last_names is None:
            last_names = [
                "smith", "johnson", "williams", "brown", "jones",
                "davis", "miller", "wilson", "moore", "taylor",
            ]

        if self.strategy == "outlook_free":
            all_addresses: list[str] = []
            for fn in first_names:
                for ln in last_names:
                    addrs = self.outlook.generate_emails(fn, ln, count=3)
                    all_addresses.extend(addrs)
                    if len(all_addresses) >= count:
                        break
                if len(all_addresses) >= count:
                    break
            addresses = list(dict.fromkeys(all_addresses))[:count]
            return [
                {
                    "email": addr,
                    "provider": "outlook",
                    "first_name": addr.split(".")[0].split("@")[0].title(),
                    "status": "planned",
                }
                for addr in addresses
            ]

        elif self.strategy == "zoho_free":
            if not domain:
                raise ValueError("Zoho strategy requires a domain parameter")
            self.zoho.domain = domain
            pairs = list(zip(first_names, last_names))
            addresses = self.zoho.generate_emails(first_last_pairs=pairs[:count])
            return [
                {
                    "email": addr,
                    "provider": "zoho",
                    "first_name": addr.split("@")[0].split(".")[0].title(),
                    "domain": domain,
                    "status": "planned",
                }
                for addr in addresses[:count]
            ]

        elif self.strategy == "custom_domain":
            if not domain:
                raise ValueError("custom_domain strategy requires a domain")
            prefixes = ["outreach", "connect", "hello", "team", "growth"]
            return [
                {
                    "email": f"{p}@{domain}",
                    "provider": "custom",
                    "first_name": p.title(),
                    "domain": domain,
                    "status": "planned",
                }
                for p in prefixes[:count]
            ]

        raise ValueError(f"Unknown strategy: {self.strategy}")

    # ------------------------------------------------------------------
    # Manual-creation checklist
    # ------------------------------------------------------------------

    def print_checklist(self) -> str:
        """Print a step-by-step checklist for manual account creation.

        The checklist adapts to the chosen strategy.

        Returns:
            The checklist as a string.
        """
        pending = [e for e in self.inboxes if e["status"] == "pending"]

        lines: list[str] = [
            f"\n{'='*64}",
            f"  Inbox Creation Checklist  ({self.strategy})",
            f"{'='*64}\n",
        ]

        if self.strategy == "outlook_free":
            lines.extend([
                "Steps to create Outlook/Hotmail accounts:\n",
                "  1. Go to https://signup.live.com/",
                "  2. Click 'Get a new email address'",
                "  3. Create each of the accounts listed below",
                "  4. Use a strong, unique password for each",
                "  5. Complete phone/SMS verification if prompted",
                "  6. Enable IMAP access (Settings > Sync email > POP and IMAP)",
                "  7. If using 2FA, generate an App Password for each account",
                "",
                "  TIP: Use different IP addresses / browsers to avoid blocks.",
                "  TIP: Space out account creation over several days.",
                "",
            ])
        elif self.strategy in ("zoho_free", "custom_domain"):
            lines.extend([
                f"Steps to create Zoho Mail accounts for {self.domain}:\n",
                "  1. Sign up at https://mail.zoho.com/signup (free plan)",
                f"  2. Add domain: {self.domain}",
                "  3. Verify domain ownership via TXT record",
                "  4. Add MX, SPF, DKIM, and DMARC DNS records",
                "     (use DNSSetup helper or ZohoInboxProvisioner.print_dns_config())",
                "  5. Create user accounts in Zoho Admin > Users",
                f"  6. Note: Zoho free plan allows up to {ZohoInboxProvisioner.MAX_FREE_USERS} users",
                "  7. Enable IMAP for each user (Settings > Mail accounts > IMAP access)",
                "",
            ])

        if pending:
            lines.append(f"Accounts to create ({len(pending)}):\n")
            for i, entry in enumerate(pending, 1):
                lines.append(f"  [ ] {i}. {entry['email']}")
            lines.append("")
        else:
            lines.append("  No pending accounts. All have been created!\n")

        lines.extend([
            "After creating each account, run:",
            "  creator.mark_created('<email>', password='<password>')",
            "",
        ])

        output = "\n".join(lines)
        print(output)
        return output

    def print_creation_checklist(self, plan: list[dict]) -> str:
        """Print step-by-step checklist for manually creating accounts.

        Legacy API -- accepts an explicit plan list.  For registry-based
        tracking use ``print_checklist()`` instead.

        Args:
            plan: List of inbox plan dicts (from ``generate_inbox_plan``).

        Returns:
            The checklist as a string.
        """
        lines = ["\n=== Inbox Creation Checklist ===\n"]

        if self.strategy == "outlook_free":
            lines.append("1. Go to https://signup.live.com")
            lines.append("2. Create each account below:")
            for i, inbox in enumerate(plan, 1):
                lines.append(f"   [ ] {i}. {inbox['email']}")
            lines.append("\n3. For each account:")
            lines.append("   [ ] Enable IMAP: Settings > Mail > Sync email > POP and IMAP")
            lines.append("   [ ] Generate app password if 2FA is on")
            lines.append("   [ ] Note down the password")
            lines.append("\n4. Record each account:")
            lines.append(
                "   python main.py inboxes add --email <email> "
                "--password <pass> --provider outlook"
            )
            lines.append("\n5. Bulk add to Instantly:")
            lines.append(
                "   python main.py inboxes bulk-add --file inboxes/sample_inboxes.csv"
            )

        elif self.strategy in ("zoho_free", "custom_domain"):
            domain = (
                plan[0].get("domain", "yourdomain.com") if plan else "yourdomain.com"
            )
            lines.append(f"1. Buy domain: {domain} ($2-3 from Namecheap/Cloudflare)")
            lines.append("2. Sign up at https://www.zoho.com/mail/ (Free plan)")
            lines.append(f"3. Add domain {domain} and verify ownership")
            lines.append("4. Add DNS records:")
            lines.append("   python main.py dns generate --domain " + domain)
            lines.append("5. Create email accounts:")
            for i, inbox in enumerate(plan, 1):
                lines.append(f"   [ ] {i}. {inbox['email']}")
            lines.append("\n6. Enable IMAP for each account")
            lines.append("7. Add to Instantly:")
            lines.append(
                "   python main.py inboxes bulk-add --file inboxes/zoho_registry.json"
            )

        output = "\n".join(lines)
        print(output)
        return output

    # ------------------------------------------------------------------
    # Status tracking
    # ------------------------------------------------------------------

    def mark_created(self, email: str, password: str) -> None:
        """Mark an account as manually created and store its password.

        Args:
            email:    The email address.
            password: The account password (or app password).
        """
        entry = self._find(email)
        if entry is None:
            raise ValueError(f"{email} is not in the registry.")
        entry["password"] = password
        entry["status"] = "verified"
        entry["verified_at"] = datetime.now(timezone.utc).isoformat()

        # Also update the provider-specific provisioner
        if self.strategy == "outlook_free":
            try:
                self.outlook.mark_verified(email, password)
            except ValueError:
                pass
        elif self.strategy in ("zoho_free", "custom_domain"):
            try:
                self.zoho.mark_verified(email, password)
            except ValueError:
                pass

        self.save()

    def mark_added_to_instantly(self, email: str) -> None:
        """Mark an account as successfully added to Instantly."""
        entry = self._find(email)
        if entry is None:
            raise ValueError(f"{email} is not in the registry.")
        entry["status"] = "added_to_instantly"
        entry["added_to_instantly_at"] = datetime.now(timezone.utc).isoformat()
        self.save()

    def get_by_status(self, status: str) -> list[dict[str, Any]]:
        """Return all inboxes with a given status.

        Args:
            status: One of ``"pending"``, ``"verified"``,
                ``"added_to_instantly"``.

        Returns:
            Filtered list of inbox dicts.
        """
        return [e for e in self.inboxes if e["status"] == status]

    def summary(self) -> dict[str, int]:
        """Return a count of inboxes by status."""
        counts: dict[str, int] = {}
        for entry in self.inboxes:
            s = entry["status"]
            counts[s] = counts.get(s, 0) + 1
        counts["total"] = len(self.inboxes)
        return counts

    # ------------------------------------------------------------------
    # Instantly integration
    # ------------------------------------------------------------------

    def get_instantly_configs(self) -> list[dict[str, Any]]:
        """Return Instantly-ready config dicts for all verified inboxes.

        Returns:
            List of dicts suitable for ``AccountManager.add_inbox(**cfg)``.
        """
        configs: list[dict[str, Any]] = []
        for entry in self.inboxes:
            if entry["status"] == "verified" and entry.get("password"):
                provider = "outlook"
                if self.strategy in ("zoho_free", "custom_domain"):
                    provider = "zoho"
                configs.append({
                    "email": entry["email"],
                    "password": entry["password"],
                    "first_name": entry["first_name"],
                    "provider": provider,
                    "daily_limit": self.daily_limit,
                    "warmup": self.warmup,
                })
        return configs

    def push_to_instantly(self, account_manager: Any) -> list[dict[str, Any]]:
        """Add all verified inboxes to Instantly via the AccountManager.

        Args:
            account_manager: An ``AccountManager`` instance from the
                ``instantly`` package.

        Returns:
            List of result dicts from ``AccountManager.add_bulk_inboxes()``.
        """
        configs = self.get_instantly_configs()
        if not configs:
            print("  No verified inboxes to add.")
            return []

        print(f"  Adding {len(configs)} inbox(es) to Instantly...")
        results = account_manager.add_bulk_inboxes(configs)

        # Update status for successful adds
        for res in results:
            if res.get("status") == "added":
                self.mark_added_to_instantly(res["email"])

        return results

    def add_all_to_instantly(
        self, accounts: list[dict], account_manager: Any
    ) -> list[dict]:
        """Add all created accounts to Instantly via AccountManager.

        Legacy API -- accepts an explicit accounts list.  For registry-based
        tracking use ``push_to_instantly()`` instead.

        Args:
            accounts:        List of account dicts with email/password/etc.
            account_manager: An ``AccountManager`` instance.

        Returns:
            List of result dicts from ``AccountManager.add_bulk_inboxes()``.
        """
        results = account_manager.add_bulk_inboxes(accounts)
        for result in results:
            if result["status"] == "added":
                email = result["email"]
                if "@outlook.com" in email or "@hotmail.com" in email:
                    try:
                        self.outlook.mark_added_to_instantly(email)
                    except ValueError:
                        pass
        return results

    # ------------------------------------------------------------------
    # CSV import / export
    # ------------------------------------------------------------------

    def export_csv(self, path: str | Path = "inboxes.csv") -> Path:
        """Export the full inbox list to a CSV file.

        Columns: email, first_name, strategy, status, created_at,
        verified_at, added_to_instantly_at.  Passwords are **not** exported
        for security.

        Args:
            path: Output CSV file path.

        Returns:
            The resolved Path of the written CSV file.
        """
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "email",
            "first_name",
            "strategy",
            "status",
            "created_at",
            "verified_at",
            "added_to_instantly_at",
        ]
        with open(out, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for entry in self.inboxes:
                writer.writerow(entry)

        print(f"  Exported {len(self.inboxes)} inboxes to {out}")
        return out.resolve()

    def export_to_csv(
        self, plan: list[dict], output_path: str = "inboxes/inbox_plan.csv"
    ) -> None:
        """Export inbox plan to CSV (legacy API).

        Args:
            plan:        List of inbox plan dicts.
            output_path: Output file path.
        """
        if not plan:
            return
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = ["email", "password", "first_name", "provider", "status"]
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for inbox in plan:
                inbox.setdefault("password", "FILL_IN")
                writer.writerow(inbox)
        print(f"  Exported plan to {output_path}")

    def import_created_accounts(self, csv_path: str | Path) -> list[dict[str, Any]]:
        """Import accounts from a CSV after the user has created them.

        The CSV should have columns: ``email``, ``password``, ``first_name``.
        Rows with a non-empty password that is not ``"FILL_IN"`` are imported.

        Args:
            csv_path: Path to the CSV file.

        Returns:
            List of imported account dicts.
        """
        imported: list[dict[str, Any]] = []
        with open(csv_path, newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                pw = row.get("password", "").strip()
                if pw and pw != "FILL_IN":
                    email = row["email"].strip()
                    entry = self._find(email)
                    if entry is not None:
                        self.mark_created(email, pw)
                    imported.append(dict(row))
        return imported

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self) -> None:
        """Persist the master inbox registry to JSON."""
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "strategy": self.strategy,
            "domain": self.domain,
            "inboxes": self.inboxes,
        }
        with open(self.registry_path, "w") as fh:
            json.dump(data, fh, indent=2)

    def load(self) -> None:
        """Load the master inbox registry from JSON."""
        with open(self.registry_path) as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            self.strategy = data.get("strategy", self.strategy)
            self.domain = data.get("domain", self.domain)
            self.inboxes = data.get("inboxes", [])
        else:
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
        s = self.summary()
        return (
            f"<BulkInboxCreator strategy={self.strategy!r} "
            f"total={s.get('total', 0)} "
            f"pending={s.get('pending', 0)} "
            f"verified={s.get('verified', 0)} "
            f"added={s.get('added_to_instantly', 0)}>"
        )
