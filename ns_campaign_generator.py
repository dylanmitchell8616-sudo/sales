#!/usr/bin/env python3
"""
Nova Scotia Campaign Generator
Generates personalized cold emails for all qualified NS leads.
Emphasizes Dylan as a Dalhousie student building AI for local businesses.
Outputs CSV ready for Instantly uploader.
"""

import csv
import json
import os
import sys
import time

try:
    import anthropic
except ImportError:
    print("pip install anthropic")
    sys.exit(1)

CONFIG_PATH = "config.json"
INPUT_FILE = "output/ns_leads_qualified.csv"
OUTPUT_FILE = "output/ns_campaign_emails.csv"

# Category-specific pain points
PAIN_POINTS = {
    "Dentist": "missed calls from new patients, front desk overwhelmed during cleanings, and no-shows eating into your schedule",
    "Dental clinic": "missed calls from new patients, front desk overwhelmed during cleanings, and no-shows eating into your schedule",
    "Orthodontist": "parents calling about consultations going to voicemail, and follow-up calls for retainer checks falling through the cracks",
    "Medical spa": "losing Botox and filler leads because calls go unanswered after hours, and rebooking lapsed clients sitting in your CRM",
    "Chiropractor": "new patient calls going to voicemail when your front desk is busy, and reactivating past patients who haven't booked in months",
    "Optometrist": "appointment requests piling up, patients calling about lens orders tying up your staff, and annual exam reminders going unsent",
    "Wellness center": "losing first-time clients when calls go unanswered, and manually following up with everyone who came for one session",
    "Hair salon": "missing booking calls during busy hours, last-minute cancellations leaving empty chairs, and clients forgetting to rebook",
    "Beauty salon": "phone ringing off the hook during appointments, walk-ins you can't track, and clients not rebooking after their first visit",
    "Massage therapist": "calls going to voicemail when you're with a client, no-shows costing you money, and past clients not rebooking",
    "Physical therapist": "intake calls going to voicemail, patients not scheduling their follow-ups, and referrals from doctors falling through",
    "Physical therapy clinic": "intake calls going to voicemail, patients not scheduling their follow-ups, and referrals from doctors falling through",
    "Barber shop": "missed calls when every chair is full, walk-in chaos, and regulars not rebooking consistently",
    "Spa": "losing high-value bookings to unanswered after-hours calls, and gift certificate buyers never converting to regulars",
    "Day spa": "losing high-value bookings to unanswered after-hours calls, and gift certificate buyers never converting to regulars",
    "Health spa": "losing high-value bookings to unanswered after-hours calls, and gift certificate buyers never converting to regulars",
    "Nail salon": "phone ringing non-stop during appointments, double-bookings, and clients not knowing when their next fill is due",
    "Skin care clinic": "consultation requests going to voicemail, and clients who did one treatment never booking the follow-up series",
    "Acupuncture clinic": "new patient calls going unanswered during sessions, and patients dropping off their treatment plan mid-way",
    "Naturopathic practitioner": "initial consultation calls going to voicemail, and follow-up scheduling falling through the cracks",
    "Counselor": "intake calls from new clients going to voicemail, and the admin burden of scheduling and rescheduling",
    "Psychologist": "potential clients calling during sessions and never calling back, and the back-and-forth of scheduling",
    "Mental health service": "potential clients calling during sessions and never calling back, and the back-and-forth of scheduling",
    "Laser hair removal service": "consultation requests going unanswered and losing them to a competitor down the street",
    "Medical clinic": "high call volume overwhelming your front desk, patients waiting on hold, and after-hours calls going to voicemail",
    "Eye care center": "appointment calls competing with walk-ins at the front desk, and annual exam reminders going unsent",
    "Hairdresser": "missing booking calls during busy hours, last-minute cancellations leaving gaps, and clients forgetting to rebook",
    "Osteopath": "new patient calls going to voicemail during treatments, and past patients not coming back for maintenance visits",
    "Facial spa": "losing consultation bookings to unanswered calls, and one-time facial clients never rebooking",
}

DEFAULT_PAIN = "missed calls costing you new clients, your front desk overwhelmed during peak hours, and past clients sitting in your database who haven't rebooked"


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def load_leads():
    leads = []
    with open(INPUT_FILE, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get('email', '').strip():
                leads.append(row)
    return leads


def generate_emails_batch(client, leads_batch, batch_num, total_batches):
    """Generate personalized emails for a batch of leads using Claude."""

    leads_info = []
    for i, lead in enumerate(leads_batch):
        category = lead.get('category', '')
        pain = PAIN_POINTS.get(category, DEFAULT_PAIN)
        leads_info.append({
            "index": i,
            "company_name": lead.get('company_name', ''),
            "category": category,
            "city": lead.get('city', ''),
            "rating": lead.get('rating', ''),
            "reviews": lead.get('reviews', ''),
            "pain_points": pain,
        })

    prompt = f"""Generate personalized cold emails for these {len(leads_batch)} Nova Scotia businesses.

SENDER CONTEXT:
- Name: Dylan Mitchell
- Student at Dalhousie University in Halifax, Nova Scotia
- Building Realside AI — AI-powered phone agents for service businesses
- Products: AI Inbound Receptionist (answers calls 24/7, books appointments) and AI Outbound Agent (follows up with leads/past clients automatically)
- Calendar: calendly.com/realsideai
- This is a LOCAL founder reaching out to LOCAL businesses — emphasize this connection

EMAIL RULES:
- Subject line: short, curiosity-driven, personal (use their company name or city). NO spam words (free, guaranteed, etc.)
- Body: 3-5 sentences MAX. Casual, friendly tone like a student who genuinely wants to help local businesses.
- MUST mention being a Dalhousie student early in the email — this builds trust and relatability
- Reference their specific business type and a pain point they'd recognize
- End with soft CTA: "Would you be open to a quick chat?" or similar (include calendly.com/realsideai)
- Do NOT use dashes (--) anywhere
- Do NOT be salesy or corporate. Be genuine, human, local.
- Each email must be UNIQUE — vary the opening, angle, and CTA
- Sign off as just "Dylan" (no last name, keep it casual)

BUSINESSES:
{json.dumps(leads_info, indent=2)}

Return a JSON array with one object per business:
[
  {{
    "index": 0,
    "subject": "the subject line",
    "body": "the email body in plain text (use \\n for line breaks)"
  }},
  ...
]

Return ONLY the JSON array, no other text."""

    for attempt in range(3):
        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}]
            )

            text = response.content[0].text.strip()
            # Extract JSON from response
            if text.startswith('['):
                emails = json.loads(text)
            else:
                # Find JSON array in response
                start = text.find('[')
                end = text.rfind(']') + 1
                emails = json.loads(text[start:end])

            print(f"  Batch {batch_num}/{total_batches}: Generated {len(emails)} emails")
            return emails

        except Exception as e:
            print(f"  Batch {batch_num} attempt {attempt+1} error: {e}")
            if attempt < 2:
                time.sleep(2)

    return []


def main():
    dry_run = '--dry-run' in sys.argv

    print("=== NS Campaign Email Generator (Dalhousie Student Angle) ===\n")

    config = load_config()
    leads = load_leads()
    print(f"Loaded {len(leads)} leads with emails")

    if dry_run:
        print(f"\n[DRY RUN] Would generate emails for {len(leads)} leads")
        for lead in leads[:5]:
            print(f"  {lead['company_name']} ({lead['category']}) - {lead['email']}")
        return

    client = anthropic.Anthropic(api_key=config['anthropic_api_key'])

    # Process in batches of 15
    BATCH_SIZE = 15
    all_results = []
    total_batches = (len(leads) + BATCH_SIZE - 1) // BATCH_SIZE

    for batch_num in range(total_batches):
        start = batch_num * BATCH_SIZE
        end = min(start + BATCH_SIZE, len(leads))
        batch = leads[start:end]

        emails = generate_emails_batch(client, batch, batch_num + 1, total_batches)

        if emails:
            for email_data in emails:
                idx = email_data.get('index', 0)
                if idx < len(batch):
                    lead = batch[idx]
                    all_results.append({
                        'email': lead['email'],
                        'company_name': lead.get('company_name', ''),
                        'domain': lead.get('domain', ''),
                        'category': lead.get('category', ''),
                        'city': lead.get('city', ''),
                        'subject': email_data.get('subject', ''),
                        'body': email_data.get('body', ''),
                    })

        # Rate limit
        if batch_num < total_batches - 1:
            time.sleep(1)

    # Write output CSV
    fieldnames = ['email', 'company_name', 'domain', 'category', 'city', 'subject', 'body']
    with open(OUTPUT_FILE, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_results)

    print(f"\n=== Done ===")
    print(f"Generated {len(all_results)} emails")
    print(f"Saved to {OUTPUT_FILE}")


if __name__ == '__main__':
    main()
