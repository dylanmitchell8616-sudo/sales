#!/usr/bin/env python3
"""
Realside AI - Apollo Lead Search Helper
Generates Apollo search URLs and filters based on ICP config.
Also provides sample contact CSVs for testing.
"""

import json
import csv
import os
import urllib.parse
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
OUTPUT_DIR = BASE_DIR / "output"


def load_icp_config():
    with open(CONFIG_DIR / "icp_config.json", "r") as f:
        return json.load(f)


def generate_apollo_search_params(icp):
    """Generate Apollo search parameters for a specific ICP vertical."""
    config = load_icp_config()
    apollo_filters = config["apollo_search_filters"]

    params = {
        "vertical": icp["vertical"],
        "titles": icp["titles"],
        "company_size": icp["company_size"],
        "revenue_range": icp["revenue_range"],
        "sub_verticals": icp["sub_verticals"],
        "location": apollo_filters["location"],
        "exclude": apollo_filters["exclude_industries"],
        "keywords": apollo_filters["keywords"],
        "technologies": apollo_filters["technologies"],
    }

    return params


def print_apollo_instructions():
    """Print step-by-step Apollo search instructions for each ICP."""
    config = load_icp_config()

    print("\n" + "=" * 70)
    print("REALSIDE AI - APOLLO LEAD SEARCH GUIDE")
    print("=" * 70)

    for icp in config["ideal_customer_profiles"]:
        params = generate_apollo_search_params(icp)
        priority = icp["priority"]

        print(f"\n{'─' * 70}")
        print(f"VERTICAL: {icp['vertical']} (Priority: {priority})")
        print(f"Estimated Deal Size: {icp['estimated_deal_size']}")
        print(f"{'─' * 70}")

        print(f"\nApollo Search Filters:")
        print(f"  Job Titles: {', '.join(params['titles'])}")
        print(f"  Company Size: {params['company_size']}")
        print(f"  Revenue: {params['revenue_range']}")
        print(f"  Sub-verticals: {', '.join(params['sub_verticals'])}")
        print(f"  Location: {params['location']}")
        print(f"  Technologies: {', '.join(params['technologies'])}")

        print(f"\n  Pain Signals to Look For:")
        for signal in icp["pain_signals"]:
            print(f"    → {signal}")

        print(f"\n  Apollo Keywords to Add:")
        for kw in params["keywords"]:
            print(f"    • {kw}")

        print(f"\n  Export Settings:")
        print(f"    • Export as CSV")
        print(f"    • Include: First Name, Last Name, Email, Company, Title, Industry, LinkedIn URL")
        print(f"    • Recommended batch size: 500-1000 per search")
        print(f"    • Verify emails before importing to Instantly")

    print(f"\n{'=' * 70}")
    print("WEEKLY LEAD SOURCING CADENCE")
    print("=" * 70)
    print("""
    Monday:    Pull 200 leads from HIGH priority verticals (Home Services, Real Estate)
    Tuesday:   Pull 200 leads from HIGH priority verticals (Insurance)
    Wednesday: Pull 100 leads from MEDIUM priority verticals (Dental/Medical)
    Thursday:  Pull 100 leads from MEDIUM priority verticals (Auto Dealers)
    Friday:    Clean lists, verify emails, import to Instantly

    Weekly total: ~800 new leads → feeds ~200 emails/day sending capacity
    """)


def generate_sample_contacts():
    """Generate a sample contacts CSV for testing the email generator."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filepath = OUTPUT_DIR / "sample_contacts.csv"

    sample_data = [
        {"first_name": "Mike", "last_name": "Johnson", "email": "mike@example-hvac.com",
         "company_name": "Johnson HVAC Solutions", "industry": "Home Services",
         "title": "Owner", "location": "Dallas, TX", "linkedin_url": ""},
        {"first_name": "Sarah", "last_name": "Williams", "email": "sarah@example-realty.com",
         "company_name": "Williams Real Estate Group", "industry": "Real Estate",
         "title": "Broker", "location": "Phoenix, AZ", "linkedin_url": ""},
        {"first_name": "David", "last_name": "Chen", "email": "david@example-insurance.com",
         "company_name": "Chen Insurance Agency", "industry": "Insurance",
         "title": "Agency Owner", "location": "Austin, TX", "linkedin_url": ""},
        {"first_name": "Lisa", "last_name": "Rodriguez", "email": "lisa@example-dental.com",
         "company_name": "Bright Smile Dental", "industry": "Dental & Medical",
         "title": "Practice Owner", "location": "Miami, FL", "linkedin_url": ""},
        {"first_name": "Tom", "last_name": "Baker", "email": "tom@example-roofing.com",
         "company_name": "Baker Roofing Co", "industry": "Home Services",
         "title": "General Manager", "location": "Atlanta, GA", "linkedin_url": ""},
    ]

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=sample_data[0].keys())
        writer.writeheader()
        writer.writerows(sample_data)

    print(f"\n✓ Sample contacts CSV created: {filepath}")
    print(f"  Use this to test: python scripts/generate_sequences.py output/sample_contacts.csv --sender-name 'Dylan' --sender-email 'dylan@realsideai.com' --sequence crm_reactivation")
    return filepath


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--sample":
        generate_sample_contacts()
    else:
        print_apollo_instructions()
        print("\nTip: Run with --sample flag to generate a test contacts CSV")
