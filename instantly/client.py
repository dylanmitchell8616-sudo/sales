"""Instantly.ai API client for cold email automation.

Supports both API v1 (legacy) and API v2 (current, Bearer token auth).
Auto-detects version based on key format.
"""

import time
import requests


class InstantlyClient:
    """Client for the Instantly.ai API v2 (with v1 fallback)."""

    BASE_URL_V2 = "https://api.instantly.ai/api/v2"
    BASE_URL_V1 = "https://api.instantly.ai/api/v1"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        })
        self.base_url = self.BASE_URL_V2

    def _request(self, method: str, endpoint: str, **kwargs):
        """Make an authenticated API request with retry logic."""
        url = f"{self.base_url}/{endpoint}"

        for attempt in range(4):
            try:
                resp = self.session.request(method, url, **kwargs)
                resp.raise_for_status()
                return resp.json() if resp.content else {}
            except requests.exceptions.HTTPError as e:
                # Don't retry 4xx errors (except 429 rate limit)
                if resp.status_code < 500 and resp.status_code != 429:
                    if attempt == 0:
                        print(f"  API error {resp.status_code}: {resp.text[:200]}")
                    raise
                if attempt == 3:
                    raise
                wait = 2 ** (attempt + 1)
                print(f"  Request failed ({e}), retrying in {wait}s...")
                time.sleep(wait)
            except requests.exceptions.RequestException as e:
                if attempt == 3:
                    raise
                wait = 2 ** (attempt + 1)
                print(f"  Request failed ({e}), retrying in {wait}s...")
                time.sleep(wait)

    def get(self, endpoint: str, **kwargs):
        return self._request("GET", endpoint, **kwargs)

    def post(self, endpoint: str, **kwargs):
        return self._request("POST", endpoint, **kwargs)

    def patch(self, endpoint: str, **kwargs):
        return self._request("PATCH", endpoint, **kwargs)

    def delete(self, endpoint: str, **kwargs):
        return self._request("DELETE", endpoint, **kwargs)

    # --- Account / Inbox endpoints (v2) ---

    def list_accounts(self, limit: int = 100, skip: int = 0) -> list:
        """List all email accounts connected to Instantly."""
        result = self.get("accounts", params={"limit": limit, "skip": skip})
        if isinstance(result, dict):
            return result.get("items", result.get("data", [result]))
        return result if isinstance(result, list) else []

    def add_account(self, email: str, first_name: str, password: str,
                    imap_host: str, imap_port: int, imap_username: str,
                    smtp_host: str, smtp_port: int, smtp_username: str,
                    warmup_enabled: bool = True, daily_limit: int = 30) -> dict:
        """Add an email sending account to Instantly."""
        payload = {
            "email": email,
            "first_name": first_name,
            "password": password,
            "imap_host": imap_host,
            "imap_port": imap_port,
            "imap_username": imap_username,
            "smtp_host": smtp_host,
            "smtp_port": smtp_port,
            "smtp_username": smtp_username,
            "warmup_enabled": warmup_enabled,
            "daily_limit": daily_limit,
        }
        return self.post("accounts", json=payload)

    def get_account(self, account_id: str) -> dict:
        """Get a specific email account."""
        return self.get(f"accounts/{account_id}")

    def delete_account(self, account_id: str) -> dict:
        """Remove an email account from Instantly."""
        return self.delete(f"accounts/{account_id}")

    def enable_warmup(self, account_id: str) -> dict:
        """Enable warmup for email account(s)."""
        return self.post("accounts/warmup/enable", json={"accounts": [account_id]})

    def disable_warmup(self, account_id: str) -> dict:
        """Disable warmup for email account(s)."""
        return self.post("accounts/warmup/disable", json={"accounts": [account_id]})

    def get_warmup_status(self, account_id: str) -> dict:
        """Get warmup analytics for an account."""
        return self.get(f"accounts/{account_id}/warmup-analytics")

    def test_account(self, account_id: str) -> dict:
        """Test IMAP/SMTP connection for an account."""
        return self.post(f"accounts/{account_id}/test-vitals")

    def pause_account(self, account_id: str) -> dict:
        """Pause an email account."""
        return self.post(f"accounts/{account_id}/pause")

    def resume_account(self, account_id: str) -> dict:
        """Resume a paused account."""
        return self.post(f"accounts/{account_id}/resume")

    # --- Campaign endpoints (v2) ---

    def list_campaigns(self, limit: int = 100, skip: int = 0) -> list:
        """List all campaigns."""
        result = self.get("campaigns", params={"limit": limit, "skip": skip})
        if isinstance(result, dict):
            return result.get("items", result.get("data", [result]))
        return result if isinstance(result, list) else []

    def get_campaign(self, campaign_id: str) -> dict:
        """Get campaign details."""
        return self.get(f"campaigns/{campaign_id}")

    def create_campaign(self, name: str, **kwargs) -> dict:
        """Create a new campaign."""
        payload = {"name": name, **kwargs}
        return self.post("campaigns", json=payload)

    def launch_campaign(self, campaign_id: str) -> dict:
        """Launch/activate a campaign."""
        return self.post(f"campaigns/{campaign_id}/activate")

    def pause_campaign(self, campaign_id: str) -> dict:
        """Pause a running campaign."""
        return self.post(f"campaigns/{campaign_id}/pause")

    def update_campaign(self, campaign_id: str, **kwargs) -> dict:
        """Update campaign settings."""
        return self.patch(f"campaigns/{campaign_id}", json=kwargs)

    def set_campaign_schedule(self, campaign_id: str, schedules: list) -> dict:
        """Set sending schedule for a campaign."""
        return self.patch(f"campaigns/{campaign_id}", json={
            "schedules": schedules,
        })

    def set_campaign_accounts(self, campaign_id: str, account_emails: list) -> dict:
        """Assign sending accounts to a campaign."""
        # V2: use account-campaign mapping endpoint
        return self.post("account-campaign-mappings", json={
            "campaign_id": campaign_id,
            "account_ids": account_emails,
        })

    def add_leads_to_campaign(self, campaign_id: str, leads: list) -> dict:
        """Add leads to a campaign."""
        return self.post("leads", json={
            "campaign_id": campaign_id,
            "leads": leads,
        })

    def set_campaign_sequences(self, campaign_id: str, sequences: list) -> dict:
        """Set email sequences for a campaign."""
        return self.patch(f"campaigns/{campaign_id}", json={
            "sequences": sequences,
        })

    # --- Lead endpoints (v2) ---

    def get_lead(self, lead_id: str) -> dict:
        """Get a specific lead."""
        return self.get(f"leads/{lead_id}")

    def get_lead_status(self, campaign_id: str, email: str) -> dict:
        """Get status of a specific lead in a campaign."""
        return self.get("leads", params={
            "campaign_id": campaign_id,
            "email": email,
        })

    def list_leads(self, campaign_id: str, limit: int = 100, skip: int = 0) -> list:
        """List leads in a campaign."""
        result = self.get("leads", params={
            "campaign_id": campaign_id,
            "limit": limit,
            "skip": skip,
        })
        if isinstance(result, dict):
            return result.get("items", result.get("data", []))
        return result if isinstance(result, list) else []

    def delete_lead(self, campaign_id: str, email: str) -> dict:
        """Delete a lead from a campaign."""
        return self.post("leads/delete", json={
            "campaign_id": campaign_id,
            "delete_list": [email],
        })

    # --- Analytics endpoints (v2) ---

    def get_campaign_summary(self, campaign_id: str) -> dict:
        """Get campaign analytics summary."""
        return self.get(f"campaigns/{campaign_id}/analytics")

    def get_campaign_steps(self, campaign_id: str) -> dict:
        """Get step-by-step analytics for a campaign."""
        return self.get(f"campaigns/{campaign_id}/step-analytics")

    def get_account_analytics(self, account_id: str) -> dict:
        """Get analytics for a specific sending account."""
        return self.get(f"accounts/{account_id}/analytics")
