"""Lead management for Instantly campaigns."""

import csv
from pathlib import Path
from .client import InstantlyClient


class LeadManager:
    """Import, deduplicate, and manage leads for campaigns."""

    def __init__(self, client: InstantlyClient, config: dict = None):
        self.client = client
        self.config = config or {}
        self.lead_config = self.config.get("leads", {})

    def import_from_csv(self, csv_path: str, campaign_id: str = None,
                        field_mapping: dict = None) -> list[dict]:
        """Import leads from a CSV file.

        Args:
            csv_path: Path to CSV file
            campaign_id: Optional - add directly to campaign
            field_mapping: Optional column name mapping, e.g.
                {"Email Address": "email", "First Name": "first_name"}
        """
        path = Path(csv_path)
        if not path.exists():
            raise FileNotFoundError(f"CSV file not found: {csv_path}")

        leads = []
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                lead = {}
                for col, val in row.items():
                    mapped_key = col.strip()
                    if field_mapping and col in field_mapping:
                        mapped_key = field_mapping[col]
                    # Normalize common field names
                    mapped_key = self._normalize_field(mapped_key)
                    if val and val.strip():
                        lead[mapped_key] = val.strip()
                if "email" in lead:
                    leads.append(lead)

        print(f"  Loaded {len(leads)} leads from {csv_path}")

        # Deduplicate
        if self.lead_config.get("auto_deduplicate", True):
            before = len(leads)
            leads = self._deduplicate(leads)
            dupes = before - len(leads)
            if dupes:
                print(f"  Removed {dupes} duplicate(s)")

        # Validate required fields
        required = self.lead_config.get("required_fields", ["email"])
        leads = self._validate_required(leads, required)

        # Add to campaign if specified
        if campaign_id and leads:
            print(f"  Adding {len(leads)} leads to campaign {campaign_id}...")
            self.client.add_leads_to_campaign(campaign_id, leads)

        return leads

    def import_from_list(self, leads: list[dict], campaign_id: str = None) -> list[dict]:
        """Import leads from a list of dicts."""
        if self.lead_config.get("auto_deduplicate", True):
            leads = self._deduplicate(leads)

        if campaign_id and leads:
            self.client.add_leads_to_campaign(campaign_id, leads)

        return leads

    def get_status(self, campaign_id: str, email: str) -> dict:
        """Get lead status in a campaign."""
        return self.client.get_lead_status(campaign_id, email)

    def list_leads(self, campaign_id: str, limit: int = 100) -> list:
        """List leads in a campaign."""
        return self.client.list_leads(campaign_id, limit=limit)

    def remove_lead(self, campaign_id: str, email: str) -> dict:
        """Remove a lead from a campaign."""
        return self.client.delete_lead(campaign_id, email)

    def generate_sample_csv(self, output_path: str = "leads.csv") -> str:
        """Generate a sample CSV file with the correct format."""
        sample_data = [
            {"email": "jane@example.com", "first_name": "Jane", "last_name": "Smith",
             "company": "Acme Corp", "title": "VP of Sales", "website": "acme.com"},
            {"email": "john@example.com", "first_name": "John", "last_name": "Doe",
             "company": "TechCo", "title": "Head of Growth", "website": "techco.io"},
        ]
        fieldnames = ["email", "first_name", "last_name", "company", "title", "website"]
        with open(output_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(sample_data)
        print(f"  Sample CSV created: {output_path}")
        return output_path

    def _deduplicate(self, leads: list[dict]) -> list[dict]:
        """Remove duplicate leads by email."""
        seen = set()
        unique = []
        for lead in leads:
            email = lead.get("email", "").lower()
            if email and email not in seen:
                seen.add(email)
                unique.append(lead)
        return unique

    def _validate_required(self, leads: list[dict], required: list[str]) -> list[dict]:
        """Filter leads missing required fields."""
        valid = []
        for lead in leads:
            if all(lead.get(f) for f in required):
                valid.append(lead)
        skipped = len(leads) - len(valid)
        if skipped:
            print(f"  Skipped {skipped} lead(s) missing required fields: {required}")
        return valid

    @staticmethod
    def _normalize_field(name: str) -> str:
        """Normalize field names to snake_case standard."""
        mapping = {
            "email": "email", "email address": "email", "e-mail": "email",
            "first name": "first_name", "firstname": "first_name",
            "first": "first_name", "fname": "first_name",
            "last name": "last_name", "lastname": "last_name",
            "last": "last_name", "lname": "last_name",
            "company": "company", "company name": "company",
            "organization": "company", "org": "company",
            "title": "title", "job title": "title", "role": "title",
            "position": "title",
            "website": "website", "url": "website", "domain": "website",
            "phone": "phone", "phone number": "phone",
            "linkedin": "linkedin", "linkedin url": "linkedin",
        }
        return mapping.get(name.lower().strip(), name.lower().strip().replace(" ", "_"))
