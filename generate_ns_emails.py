#!/usr/bin/env python3
"""
Generate personalized NS campaign emails using templates.
No external API needed — uses category-specific templates with the Dalhousie student angle.
"""

import csv
import random

INPUT_FILE = "output/ns_leads_qualified.csv"
OUTPUT_FILE = "output/ns_campaign_emails.csv"

# Category-specific pain point lines
PAIN_LINES = {
    "Dentist": [
        "I know how many calls dental offices miss during cleanings and procedures",
        "Most dental practices I've talked to lose 5-10 new patient calls a week to voicemail",
        "I've been researching how many new patient calls go unanswered at dental offices during peak hours",
    ],
    "Dental clinic": [
        "I know how many calls dental clinics miss during procedures",
        "Most dental clinics I've talked to lose new patient calls every week to voicemail",
        "I've been looking into how dental clinics handle call volume during busy hours",
    ],
    "Orthodontist": [
        "I know parents calling about braces consultations hate getting voicemail",
        "Most ortho offices I've talked to lose consultation leads because the front desk is swamped",
    ],
    "Medical spa": [
        "I've been looking at how many Botox and filler inquiries med spas lose to missed after-hours calls",
        "Most med spas I've talked to have hundreds of past clients in their CRM who haven't rebooked",
        "I know how competitive the med spa space is in Nova Scotia, and speed-to-lead really matters",
    ],
    "Chiropractor": [
        "I know chiropractic offices get slammed with calls between adjustments and it's tough to keep up",
        "Most chiro practices I've talked to have past patients who dropped off and never came back",
        "I've been looking at how many new patient calls go to voicemail at chiropractic offices",
    ],
    "Optometrist": [
        "I know optometry clinics get overwhelmed with appointment calls, especially during exam season",
        "Most eye care practices I've talked to struggle with annual recall reminders falling through the cracks",
    ],
    "Wellness center": [
        "I know wellness centres lose a lot of first-time clients when calls go unanswered",
        "Most wellness businesses I've talked to struggle to get one-time visitors to rebook",
    ],
    "Hair salon": [
        "I know how hard it is to answer booking calls when every stylist is mid-cut",
        "Most salons I've talked to lose bookings because the phone rings during busy hours and nobody can grab it",
    ],
    "Beauty salon": [
        "I know how impossible it is to answer the phone when you're with a client",
        "Most beauty salons I've talked to lose walk-in and call-in bookings during peak hours",
    ],
    "Massage therapist": [
        "I know every missed call during a session is potentially a lost booking",
        "Most massage therapists I've talked to say the phone is their biggest headache since they can't answer mid-session",
    ],
    "Physical therapist": [
        "I know PT clinics lose referral patients when intake calls go to voicemail",
        "Most physio practices I've talked to struggle with patients not scheduling their follow-ups",
    ],
    "Physical therapy clinic": [
        "I know PT clinics lose referral patients when intake calls go to voicemail",
        "Most physiotherapy clinics I've talked to have patients dropping off after their first few visits",
    ],
    "Barber shop": [
        "I know how chaotic it gets when the phone's ringing and every chair is full",
        "Most barber shops I've talked to miss calls from new clients during their busiest hours",
    ],
    "Spa": [
        "I know spas lose high-value bookings when after-hours calls go to voicemail",
        "Most spas I've talked to have gift certificate buyers who never convert into regular clients",
    ],
    "Day spa": [
        "I know day spas lose their best bookings to unanswered after-hours calls",
    ],
    "Health spa": [
        "I know health spas lose bookings when calls go unanswered during treatments",
    ],
    "Nail salon": [
        "I know the phone never stops ringing at nail salons, especially on weekends",
        "Most nail salons I've talked to deal with double-bookings and no-shows constantly",
    ],
    "Skin care clinic": [
        "I know skin care clinics lose consultation leads when calls go to voicemail",
    ],
    "Acupuncture clinic": [
        "I know acupuncture clinics can't answer the phone during treatments",
    ],
    "Naturopathic practitioner": [
        "I know naturopathic practices miss calls during consultations all the time",
    ],
    "Counselor": [
        "I know counsellors miss intake calls because you're in session all day",
    ],
    "Psychologist": [
        "I know psychologists can't pick up the phone during sessions, and potential clients rarely call back",
    ],
    "Mental health service": [
        "I know mental health practices lose new client inquiries when calls go unanswered during sessions",
    ],
    "Laser hair removal service": [
        "I know laser clinics lose consultation leads to competitors when calls go unanswered",
    ],
    "Medical clinic": [
        "I know medical clinics deal with overwhelming call volume and patients waiting on hold",
    ],
    "Eye care center": [
        "I know eye care centres juggle walk-ins and phone calls at the same time",
    ],
    "Hairdresser": [
        "I know how hard it is to answer booking calls when you're mid-appointment",
    ],
    "Osteopath": [
        "I know osteopathic practices miss calls during treatments all the time",
    ],
}

DEFAULT_PAIN_LINES = [
    "I know how many calls service businesses miss during their busiest hours",
    "Most local businesses I've talked to lose new clients just because no one could pick up the phone",
    "I've been researching how many potential clients local businesses lose to missed calls and slow follow-up",
]

# Subject line templates
SUBJECT_TEMPLATES = [
    "Quick question for {company_short}",
    "{company_short} + AI (from a Dal student)",
    "Idea for {company_short}",
    "Saw {company_short} in {city}",
    "{city} student with an idea for {company_short}",
    "Would this help {company_short}?",
    "For {company_short} re: missed calls",
    "Dal student, quick question for {company_short}",
]

# Email body templates
BODY_TEMPLATES = [
    """Hi there,

I'm Dylan, a student at Dalhousie University here in Halifax. I've been building an AI phone agent for local service businesses and wanted to reach out to {company_name}.

{pain_line}. So I built something that answers every call 24/7, books appointments, and follows up with past clients automatically.

Would you be open to a quick 10-minute chat to see if it could work for {company_short}? Here's my calendar: calendly.com/realsideai

Cheers,
Dylan""",

    """Hi,

My name's Dylan, I'm a Dalhousie student in Halifax building AI for local businesses. I came across {company_name} and thought this might be relevant.

{pain_line}. I built an AI receptionist that picks up every call, books appointments, and re-engages past clients sitting in your system.

No pressure at all, but if you're curious I'd love to show you how it works: calendly.com/realsideai

Best,
Dylan""",

    """Hey,

I'm a Dalhousie student working on something I think could help {company_name}.

{pain_line}. I've built an AI that handles your incoming calls 24/7, books appointments into your calendar, and automatically follows up with clients who haven't been in for a while.

Would a quick chat be worth your time? Happy to walk you through it: calendly.com/realsideai

Dylan""",

    """Hi,

I'm Dylan from Dalhousie University. I've been building AI phone agents specifically for {category_lower}s in Nova Scotia and wanted to connect with {company_name}.

{pain_line}. What I've built answers every call, handles scheduling, and can even re-engage old clients who dropped off.

If you're open to it, I'd love 10 minutes to show you: calendly.com/realsideai

Talk soon,
Dylan""",

    """Hey there,

I'm a student at Dal here in Halifax, and I've been working on an AI receptionist built for local businesses like {company_name}.

{pain_line}. The AI I built picks up every single call, books appointments, and texts clients back if they called after hours.

Would you be open to a quick demo? I promise it's only 10 minutes: calendly.com/realsideai

Dylan""",

    """Hi,

Quick intro: I'm Dylan, a Dalhousie student building AI tools for local {city} businesses. Thought {company_name} might find this interesting.

{pain_line}. I've put together an AI agent that answers calls around the clock, books appointments, and brings back past clients who haven't visited in months.

Worth a quick look? Here's my calendar if so: calendly.com/realsideai

Cheers,
Dylan""",
]


def shorten_company(name):
    """Create a short version of company name."""
    # Remove common suffixes
    for suffix in [' Inc', ' Inc.', ' Ltd', ' Ltd.', ' LLC', ' Centre', ' Center',
                   ' Clinic', ' Group', ' Associates', ' & Associates', ' Studio',
                   ' Dental', ' Chiropractic', ' Optometry', ' Wellness']:
        if name.endswith(suffix) and len(name) > len(suffix) + 3:
            name = name[:-len(suffix)].strip()
    # Remove "Dr. " prefix
    if name.startswith('Dr. '):
        name = name[4:]
    # Truncate if still too long
    if len(name) > 30:
        name = name[:30].rsplit(' ', 1)[0]
    return name.strip()


def generate_email(lead):
    """Generate a personalized email for a single lead."""
    company = lead.get('company_name', 'your business')
    company_short = shorten_company(company)
    category = lead.get('category', '')
    city = lead.get('city', 'Nova Scotia')
    category_lower = category.lower() if category else 'business'

    # Pick pain line
    pain_lines = PAIN_LINES.get(category, DEFAULT_PAIN_LINES)
    pain_line = random.choice(pain_lines)

    # Pick subject
    subject_template = random.choice(SUBJECT_TEMPLATES)
    subject = subject_template.format(
        company_short=company_short,
        city=city,
    )

    # Pick body template
    body_template = random.choice(BODY_TEMPLATES)
    body = body_template.format(
        company_name=company,
        company_short=company_short,
        pain_line=pain_line,
        city=city,
        category_lower=category_lower,
    )

    return subject, body


def main():
    print("=== NS Campaign Email Generator (Template-Based) ===\n")

    # Load leads with emails
    leads = []
    with open(INPUT_FILE, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get('email', '').strip():
                leads.append(row)

    print(f"Loaded {len(leads)} leads with emails")

    # Generate emails
    results = []
    for lead in leads:
        subject, body = generate_email(lead)
        results.append({
            'email': lead['email'],
            'company_name': lead.get('company_name', ''),
            'domain': lead.get('domain', ''),
            'category': lead.get('category', ''),
            'city': lead.get('city', ''),
            'subject': subject,
            'body': body,
        })

    # Write output
    fieldnames = ['email', 'company_name', 'domain', 'category', 'city', 'subject', 'body']
    with open(OUTPUT_FILE, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    print(f"Generated {len(results)} personalized emails")
    print(f"Saved to {OUTPUT_FILE}")

    # Show samples
    print("\n--- Sample Emails ---")
    samples = random.sample(results, min(3, len(results)))
    for s in samples:
        print(f"\nTO: {s['email']} ({s['company_name']})")
        print(f"SUBJECT: {s['subject']}")
        print(f"BODY:\n{s['body']}")
        print("-" * 50)


if __name__ == '__main__':
    main()
