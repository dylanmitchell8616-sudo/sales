"""
Lead generation scraper for cold outreach campaigns.

Supports Apollo.io people search, Google Maps Places API,
and direct website scraping for email discovery.

Target niches: dental, HVAC, roofing, insurance, private clinics,
blue collar services.
"""

import csv
import os
import re
import time
import logging
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

EMAIL_REGEX = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
)

# Common junk emails to filter out
JUNK_EMAIL_DOMAINS = {
    "example.com",
    "sentry.io",
    "wixpress.com",
    "wordpress.com",
}
JUNK_EMAIL_PREFIXES = {
    "noreply",
    "no-reply",
    "mailer-daemon",
    "postmaster",
}

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}

REQUEST_TIMEOUT = 10  # seconds
RATE_LIMIT_DELAY = 1.0  # seconds between requests

CONTACT_PATHS = [
    "/contact",
    "/contact-us",
    "/about",
    "/about-us",
    "/contact.html",
    "/contact-us.html",
]


def _is_valid_email(email: str) -> bool:
    """Filter out junk or invalid-looking emails."""
    email = email.lower().strip()
    if not email or len(email) > 254:
        return False
    local, _, domain = email.partition("@")
    if not domain:
        return False
    if domain in JUNK_EMAIL_DOMAINS:
        return False
    if local in JUNK_EMAIL_PREFIXES:
        return False
    # Skip image file extensions mistakenly captured
    if domain.endswith((".png", ".jpg", ".jpeg", ".gif", ".svg")):
        return False
    return True


class LeadScraper:
    """Scrapes leads from Apollo.io, Google Maps, and websites."""

    def __init__(self):
        self.apollo_api_key = os.getenv("APOLLO_API_KEY", "")
        self.google_maps_api_key = os.getenv("GOOGLE_MAPS_API_KEY", "")
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self._last_request_time = 0.0

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    def _rate_limit(self):
        """Enforce minimum delay between outbound requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < RATE_LIMIT_DELAY:
            time.sleep(RATE_LIMIT_DELAY - elapsed)
        self._last_request_time = time.time()

    # ------------------------------------------------------------------
    # Apollo.io
    # ------------------------------------------------------------------

    def scrape_apollo(self, niche: str, location: str, limit: int = 100) -> list[dict]:
        """Search Apollo.io for people matching *niche* and *location*.

        Returns up to *limit* lead dicts with keys:
            email, first_name, last_name, company, title, website, linkedin
        """
        if not self.apollo_api_key:
            raise ValueError(
                "APOLLO_API_KEY environment variable is not set. "
                "Sign up at https://www.apollo.io/ for a free API key."
            )

        url = "https://api.apollo.io/v1/mixed_people/search"
        leads: list[dict] = []
        page = 1
        per_page = min(limit, 100)  # Apollo caps at 100 per page

        while len(leads) < limit:
            self._rate_limit()

            payload = {
                "api_key": self.apollo_api_key,
                "q_organization_keyword_tags": [niche],
                "person_locations": [location],
                "page": page,
                "per_page": per_page,
            }
            headers = {
                "Content-Type": "application/json",
                "Cache-Control": "no-cache",
            }

            try:
                resp = self.session.post(url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
                resp.raise_for_status()
                data = resp.json()
            except requests.RequestException as exc:
                logger.error("Apollo API request failed (page %d): %s", page, exc)
                break

            people = data.get("people") or []
            if not people:
                logger.info("Apollo returned no more results at page %d.", page)
                break

            for person in people:
                if len(leads) >= limit:
                    break

                org = person.get("organization") or {}
                lead = {
                    "email": person.get("email") or "",
                    "first_name": person.get("first_name") or "",
                    "last_name": person.get("last_name") or "",
                    "company": org.get("name") or "",
                    "title": person.get("title") or "",
                    "website": org.get("website_url") or "",
                    "linkedin": person.get("linkedin_url") or "",
                }
                leads.append(lead)

            page += 1

            # If we got fewer than requested, there are no more pages
            if len(people) < per_page:
                break

        logger.info("Apollo: collected %d leads for niche=%s, location=%s", len(leads), niche, location)
        return leads

    # ------------------------------------------------------------------
    # Google Maps Places API
    # ------------------------------------------------------------------

    def scrape_google_maps(self, query: str, limit: int = 100) -> list[dict]:
        """Search Google Maps Places API for businesses matching *query*.

        Returns up to *limit* lead dicts with keys:
            business_name, address, phone, website, email
        """
        if not self.google_maps_api_key:
            raise ValueError(
                "GOOGLE_MAPS_API_KEY environment variable is not set. "
                "Get one at https://console.cloud.google.com/"
            )

        text_search_url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
        details_url = "https://maps.googleapis.com/maps/api/place/details/json"

        leads: list[dict] = []
        params = {
            "query": query,
            "key": self.google_maps_api_key,
        }

        while len(leads) < limit:
            self._rate_limit()

            try:
                resp = self.session.get(text_search_url, params=params, timeout=REQUEST_TIMEOUT)
                resp.raise_for_status()
                data = resp.json()
            except requests.RequestException as exc:
                logger.error("Google Maps text search failed: %s", exc)
                break

            if data.get("status") != "OK":
                logger.warning("Google Maps API status: %s", data.get("status"))
                break

            results = data.get("results") or []
            if not results:
                break

            for place in results:
                if len(leads) >= limit:
                    break

                place_id = place.get("place_id")
                if not place_id:
                    continue

                # Fetch place details for phone and website
                self._rate_limit()
                try:
                    detail_resp = self.session.get(
                        details_url,
                        params={
                            "place_id": place_id,
                            "fields": "name,formatted_address,formatted_phone_number,website",
                            "key": self.google_maps_api_key,
                        },
                        timeout=REQUEST_TIMEOUT,
                    )
                    detail_resp.raise_for_status()
                    detail = detail_resp.json().get("result") or {}
                except requests.RequestException as exc:
                    logger.error("Google Maps detail request failed for %s: %s", place_id, exc)
                    detail = {}

                website = detail.get("website") or ""
                email = ""

                # Attempt to scrape an email from the business website
                if website:
                    emails = self._scrape_emails_from_site(website)
                    if emails:
                        email = emails[0]

                lead = {
                    "business_name": detail.get("name") or place.get("name") or "",
                    "address": detail.get("formatted_address") or place.get("formatted_address") or "",
                    "phone": detail.get("formatted_phone_number") or "",
                    "website": website,
                    "email": email,
                }
                leads.append(lead)

            # Handle pagination via next_page_token
            next_token = data.get("next_page_token")
            if not next_token or len(leads) >= limit:
                break

            # Google requires a short delay before next_page_token becomes valid
            time.sleep(2)
            params = {
                "pagetoken": next_token,
                "key": self.google_maps_api_key,
            }

        logger.info("Google Maps: collected %d leads for query=%s", len(leads), query)
        return leads

    # ------------------------------------------------------------------
    # Website email scraping
    # ------------------------------------------------------------------

    def _scrape_emails_from_site(self, base_url: str) -> list[str]:
        """Scrape a single website for email addresses.

        Checks the homepage and common contact pages.
        Returns a deduplicated list of emails found.
        """
        if not base_url.startswith(("http://", "https://")):
            base_url = "https://" + base_url

        # Normalise trailing slash
        parsed = urlparse(base_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"

        urls_to_check = [base_url]
        for path in CONTACT_PATHS:
            urls_to_check.append(urljoin(origin + "/", path))

        found_emails: set[str] = set()

        for page_url in urls_to_check:
            self._rate_limit()
            try:
                resp = self.session.get(page_url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
                if resp.status_code != 200:
                    continue
                content_type = resp.headers.get("Content-Type", "")
                if "text/html" not in content_type:
                    continue
            except requests.RequestException:
                continue

            # Search raw HTML — catches mailto: links and visible text
            raw_emails = EMAIL_REGEX.findall(resp.text)
            for email in raw_emails:
                if _is_valid_email(email):
                    found_emails.add(email.lower())

            # Also parse with BeautifulSoup for mailto: links
            try:
                soup = BeautifulSoup(resp.text, "html.parser")
                for anchor in soup.find_all("a", href=True):
                    href = anchor["href"]
                    if href.startswith("mailto:"):
                        addr = href.replace("mailto:", "").split("?")[0].strip()
                        if _is_valid_email(addr):
                            found_emails.add(addr.lower())
            except Exception:
                pass

        return sorted(found_emails)

    def find_emails_from_websites(self, websites: list[str]) -> dict[str, list[str]]:
        """Given a list of website URLs, return a mapping of website -> emails found.

        Checks homepage, /contact, /about, /contact-us for each site.
        """
        results: dict[str, list[str]] = {}
        for site in websites:
            logger.info("Scraping emails from %s", site)
            emails = self._scrape_emails_from_site(site)
            results[site] = emails
        return results

    # ------------------------------------------------------------------
    # Enrich
    # ------------------------------------------------------------------

    def enrich_leads(self, leads: list[dict]) -> list[dict]:
        """For leads that have a website but no email, attempt website scraping."""
        enriched = 0
        for lead in leads:
            email = lead.get("email") or ""
            website = lead.get("website") or ""
            if not email and website:
                found = self._scrape_emails_from_site(website)
                if found:
                    lead["email"] = found[0]
                    enriched += 1
        logger.info("Enriched %d leads with emails via website scraping.", enriched)
        return leads

    # ------------------------------------------------------------------
    # Search & export
    # ------------------------------------------------------------------

    def search_and_export(
        self,
        niche: str,
        location: str,
        source: str = "apollo",
        limit: int = 100,
        output_csv: str = "leads/scraped_leads.csv",
    ) -> list[dict]:
        """One-shot: scrape leads, deduplicate, and export to CSV.

        Args:
            niche: Business vertical (e.g. "dental", "HVAC", "roofing").
            location: Geographic target (e.g. "Texas, United States").
            source: "apollo" or "google_maps".
            limit: Maximum leads to collect.
            output_csv: Path for the exported CSV file.

        Returns:
            Deduplicated list of lead dicts.
        """
        # 1. Scrape from chosen source
        if source == "apollo":
            raw_leads = self.scrape_apollo(niche, location, limit=limit)
        elif source == "google_maps":
            query = f"{niche} in {location}"
            raw_leads = self.scrape_google_maps(query, limit=limit)
        else:
            raise ValueError(f"Unknown source: {source!r}. Use 'apollo' or 'google_maps'.")

        # 2. Enrich leads missing emails
        raw_leads = self.enrich_leads(raw_leads)

        # 3. Deduplicate by email (keep first occurrence; skip blanks)
        seen_emails: set[str] = set()
        leads: list[dict] = []
        for lead in raw_leads:
            email = (lead.get("email") or "").lower().strip()
            if email:
                if email in seen_emails:
                    continue
                seen_emails.add(email)
            leads.append(lead)

        # 4. Export to CSV (Instantly-compatible columns)
        self._export_csv(leads, output_csv, source)

        logger.info(
            "search_and_export complete: %d leads (%d unique emails) written to %s",
            len(leads),
            len(seen_emails),
            output_csv,
        )
        return leads

    @staticmethod
    def _export_csv(leads: list[dict], path: str, source: str):
        """Write leads to a CSV file compatible with Instantly import."""
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

        if source == "apollo":
            fieldnames = [
                "email",
                "first_name",
                "last_name",
                "company",
                "title",
                "website",
                "linkedin",
            ]
        else:
            fieldnames = [
                "email",
                "business_name",
                "address",
                "phone",
                "website",
            ]

        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(leads)


# ----------------------------------------------------------------------
# CLI convenience
# ----------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description="Scrape leads for cold outreach.")
    parser.add_argument("niche", help="Business niche (dental, HVAC, roofing, insurance, clinics, etc.)")
    parser.add_argument("location", help="Target location (e.g. 'Texas, United States')")
    parser.add_argument("--source", default="apollo", choices=["apollo", "google_maps"])
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--output", default="leads/scraped_leads.csv")
    args = parser.parse_args()

    scraper = LeadScraper()
    results = scraper.search_and_export(
        niche=args.niche,
        location=args.location,
        source=args.source,
        limit=args.limit,
        output_csv=args.output,
    )
    print(f"Done. {len(results)} leads saved to {args.output}")
