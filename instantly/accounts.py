"""Email account management for Instantly."""

from .client import InstantlyClient


# SMTP/IMAP settings for common free email providers
PROVIDER_SETTINGS = {
    "outlook": {
        "imap_host": "outlook.office365.com",
        "imap_port": 993,
        "smtp_host": "smtp-mail.outlook.com",
        "smtp_port": 587,
    },
    "gmail": {
        "imap_host": "imap.gmail.com",
        "imap_port": 993,
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 587,
    },
    "zoho": {
        "imap_host": "imap.zoho.com",
        "imap_port": 993,
        "smtp_host": "smtp.zoho.com",
        "smtp_port": 587,
    },
    "yahoo": {
        "imap_host": "imap.mail.yahoo.com",
        "imap_port": 993,
        "smtp_host": "smtp.mail.yahoo.com",
        "smtp_port": 587,
    },
}


class AccountManager:
    """Manage email sending accounts in Instantly."""

    def __init__(self, client: InstantlyClient, config: dict = None):
        self.client = client
        self.config = config or {}

    def add_inbox(self, email: str, password: str, first_name: str,
                  provider: str = None, daily_limit: int = 30,
                  warmup: bool = True,
                  custom_smtp: dict = None, custom_imap: dict = None) -> dict:
        """Add an email inbox to Instantly.

        Args:
            email: The email address
            password: Email password or app password
            first_name: Sender's first name
            provider: Auto-detect SMTP/IMAP from provider name
                      ("outlook", "gmail", "zoho", "yahoo")
            daily_limit: Max emails per day for this account
            warmup: Enable warmup on add
            custom_smtp: Override SMTP settings {host, port}
            custom_imap: Override IMAP settings {host, port}
        """
        # Determine SMTP/IMAP settings
        if custom_smtp and custom_imap:
            smtp = custom_smtp
            imap = custom_imap
        elif provider and provider.lower() in PROVIDER_SETTINGS:
            settings = PROVIDER_SETTINGS[provider.lower()]
            smtp = {"host": settings["smtp_host"], "port": settings["smtp_port"]}
            imap = {"host": settings["imap_host"], "port": settings["imap_port"]}
        else:
            # Try to auto-detect from email domain
            domain = email.split("@")[1].lower()
            provider_key = self._detect_provider(domain)
            if provider_key:
                settings = PROVIDER_SETTINGS[provider_key]
                smtp = {"host": settings["smtp_host"], "port": settings["smtp_port"]}
                imap = {"host": settings["imap_host"], "port": settings["imap_port"]}
            else:
                raise ValueError(
                    f"Cannot auto-detect SMTP/IMAP for domain {domain}. "
                    f"Provide provider name or custom_smtp/custom_imap settings."
                )

        print(f"  Adding inbox: {email} ({smtp['host']})")
        result = self.client.add_account(
            email=email,
            first_name=first_name,
            password=password,
            imap_host=imap["host"],
            imap_port=imap["port"],
            imap_username=email,
            smtp_host=smtp["host"],
            smtp_port=smtp["port"],
            smtp_username=email,
            warmup_enabled=warmup,
            daily_limit=daily_limit,
        )
        return result

    def add_bulk_inboxes(self, inboxes: list[dict]) -> list[dict]:
        """Add multiple inboxes at once.

        Args:
            inboxes: List of dicts, each with keys:
                email, password, first_name, provider (optional)
        """
        results = []
        for inbox in inboxes:
            try:
                result = self.add_inbox(**inbox)
                results.append({"email": inbox["email"], "status": "added", "result": result})
                print(f"  [OK] {inbox['email']}")
            except Exception as e:
                results.append({"email": inbox["email"], "status": "error", "error": str(e)})
                print(f"  [FAIL] {inbox['email']}: {e}")
        return results

    def list_all(self) -> list:
        """List all connected email accounts."""
        return self.client.list_accounts()

    def remove(self, email: str) -> dict:
        """Remove an email account."""
        return self.client.delete_account(email)

    def test_connection(self, email: str) -> dict:
        """Test SMTP/IMAP connection for an account."""
        return self.client.test_account(email)

    def enable_warmup(self, email: str) -> dict:
        """Enable warmup for an account."""
        return self.client.enable_warmup(email)

    def disable_warmup(self, email: str) -> dict:
        """Disable warmup for an account."""
        return self.client.disable_warmup(email)

    def warmup_status(self, email: str) -> dict:
        """Get warmup status."""
        return self.client.get_warmup_status(email)

    def bulk_enable_warmup(self) -> list:
        """Enable warmup on all accounts."""
        accounts = self.list_all()
        results = []
        for acc in accounts:
            email = acc if isinstance(acc, str) else acc.get("email", "")
            if email:
                self.enable_warmup(email)
                results.append(email)
                print(f"  Warmup enabled: {email}")
        return results

    def get_analytics(self, email: str) -> dict:
        """Get sending analytics for an account."""
        return self.client.get_account_analytics(email)

    @staticmethod
    def _detect_provider(domain: str) -> str | None:
        """Detect email provider from domain."""
        domain_map = {
            "outlook.com": "outlook",
            "hotmail.com": "outlook",
            "live.com": "outlook",
            "gmail.com": "gmail",
            "zoho.com": "zoho",
            "yahoo.com": "yahoo",
        }
        return domain_map.get(domain)
