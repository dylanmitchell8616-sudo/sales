#!/usr/bin/env python3
"""
Parallel Email Scraper — scrapes emails from websites in a CSV chunk.
Usage:
    python parallel_email_scraper.py <input_csv> <start_idx> <end_idx> <output_csv>

Reads rows [start_idx, end_idx) from input_csv that have a website but no email,
scrapes emails, and writes results to output_csv.
"""
import csv
import re
import sys
import os
from urllib.parse import urljoin

try:
    import requests
except ImportError:
    print("Error: requests required")
    sys.exit(1)

EMAIL_REGEX = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')
JUNK_PATTERNS = ["example.com", "sentry.io", "wixpress.com", "wordpress.com",
                 "googleapis.com", "google.com", "facebook.com", "twitter.com",
                 "instagram.com", "linkedin.com", "squarespace.com", "godaddy.com",
                 "wpengine.com", "cloudflare.com", "@2x.", "@3x.", ".png", ".jpg",
                 ".svg", ".gif", ".webp", ".css", ".js"]

def is_valid_email(email: str) -> bool:
    e = email.lower().strip()
    if len(e) > 100 or len(e) < 5:
        return False
    for junk in JUNK_PATTERNS:
        if junk in e:
            return False
    if e.startswith("noreply@") or e.startswith("no-reply@"):
        return False
    return True

def scrape_email_from_website(website: str, timeout: int = 10) -> str:
    if not website:
        return ""
    if not website.startswith("http"):
        website = "https://" + website
    paths_to_try = ["", "/contact", "/contact-us", "/about", "/about-us"]
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    found_emails = []
    for path in paths_to_try:
        try:
            url = urljoin(website, path)
            resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
            if resp.status_code != 200:
                continue
            raw_emails = EMAIL_REGEX.findall(resp.text)
            for email in raw_emails:
                if is_valid_email(email):
                    found_emails.append(email.lower().strip())
            if found_emails:
                break
        except Exception:
            continue
    if not found_emails:
        return ""
    domain = website.replace("https://", "").replace("http://", "").split("/")[0].lower()
    domain_emails = [e for e in found_emails if domain in e]
    if domain_emails:
        for prefix in ["info@", "contact@", "hello@", "office@", "admin@"]:
            for e in domain_emails:
                if e.startswith(prefix):
                    return e
        return domain_emails[0]
    return found_emails[0]

def main():
    input_csv = sys.argv[1]
    start_idx = int(sys.argv[2])
    end_idx = int(sys.argv[3])
    output_csv = sys.argv[4]

    # Read all rows
    with open(input_csv, "r") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        all_rows = list(reader)

    # Filter to rows without email but with website, within our range
    no_email_rows = [(i, row) for i, row in enumerate(all_rows)
                     if not row.get("email") and row.get("website")]

    # Take our chunk
    chunk = no_email_rows[start_idx:end_idx]
    print(f"Processing chunk [{start_idx}:{end_idx}] — {len(chunk)} websites to scrape")

    results = []  # list of (original_index, email)
    found = 0
    for count, (orig_idx, row) in enumerate(chunk):
        email = scrape_email_from_website(row["website"])
        if email:
            results.append((orig_idx, email))
            found += 1
        if (count + 1) % 25 == 0:
            print(f"  {count + 1}/{len(chunk)} done, {found} emails found")

    print(f"Done! Found {found} emails out of {len(chunk)} websites")

    # Write results
    with open(output_csv, "w") as f:
        writer = csv.writer(f)
        writer.writerow(["row_index", "email"])
        for idx, email in results:
            writer.writerow([idx, email])

    print(f"Saved to {output_csv}")

if __name__ == "__main__":
    main()
