#!/usr/bin/env python3
"""Merge parallel email scrape results back into the master CSV."""
import csv
import glob
import sys

def main():
    input_csv = sys.argv[1]  # e.g., output/ns_leads_all.csv
    pattern = sys.argv[2]    # e.g., output/email_chunk_*.csv

    # Read master CSV
    with open(input_csv, "r") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    # Build index of no-email rows (same order as parallel_email_scraper.py)
    no_email_indices = [i for i, row in enumerate(rows)
                        if not row.get("email") and row.get("website")]

    # Read all chunk results
    chunk_files = sorted(glob.glob(pattern))
    updates = 0
    for chunk_file in chunk_files:
        with open(chunk_file, "r") as f:
            reader = csv.DictReader(f)
            for result in reader:
                no_email_idx = int(result["row_index"])
                email = result["email"]
                if no_email_idx < len(no_email_indices):
                    actual_row_idx = no_email_indices[no_email_idx]
                    rows[actual_row_idx]["email"] = email
                    updates += 1

    # Write updated CSV
    with open(input_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    total_with_email = len([r for r in rows if r.get("email")])
    print(f"Merged {updates} new emails from {len(chunk_files)} chunk files")
    print(f"Total leads with email: {total_with_email}/{len(rows)}")

if __name__ == "__main__":
    main()
