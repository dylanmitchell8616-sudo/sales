#!/usr/bin/env python3
"""
Generate fully custom emails + follow-ups for Halifax business owners.
Each email is unique per owner, references their name, title, company, and industry.
Dalhousie student angle throughout.
"""

import csv
import json
import random

INPUT_FILE = "output/halifax_owners_enriched.csv"
OUTPUT_FILE = "output/owner_campaign_emails.csv"

# Industry-specific pain points and hooks
INDUSTRY_HOOKS = {
    "Construction": {
        "pain": "I know contractors miss calls from potential clients when they're on-site all day",
        "value": "answers every call from homeowners and GCs, qualifies the job, and books estimates into your calendar",
        "followup_hooks": [
            "I was thinking about how many estimate requests {company_name} might miss when the crew is on-site",
            "Quick follow-up. A contractor in Halifax told me he was losing 3-4 jobs a week just from missed calls",
            "Last thought. Our AI books estimates directly into your calendar so you never lose a lead to voicemail again",
        ],
    },
    "Insurance": {
        "pain": "I know insurance brokers have thousands of clients in the CRM that haven't been contacted in months",
        "value": "calls through your CRM list, re-engages past clients, identifies upsell opportunities, and books policy reviews directly into your calendar",
        "followup_hooks": [
            "Following up. I was thinking about how many lapsed clients are sitting in {company_name}'s CRM right now with no outreach",
            "Quick thought. An insurance broker told me he reactivated 22 policies in the first month just by having AI call his old book of business",
            "Last note. Our AI calls your CRM list, finds clients who need policy reviews, and books them straight into your calendar automatically",
        ],
    },
    "Healthcare": {
        "pain": "I know healthcare practices lose patient calls when the front desk is busy or after hours",
        "value": "answers every patient call 24/7, books appointments, and follows up with patients who haven't been in for a while",
        "followup_hooks": [
            "Following up. I was thinking about how many new patient calls {company_name} might miss during appointments",
            "Quick thought. A clinic owner here told me they recovered 15 hours/week of admin time with an AI receptionist",
            "Last note. Our AI can also re-engage patients who haven't booked in 6+ months, bringing them back automatically",
        ],
    },
    "Beauty": {
        "pain": "I know salons and spas miss booking calls when every stylist is with a client",
        "value": "answers every booking call, schedules appointments, and texts clients reminders so you get fewer no-shows",
        "followup_hooks": [
            "Following up. I was wondering how {company_name} handles booking calls during your busiest hours",
            "Quick thought. A salon owner here in Halifax cut her no-shows by 40% just with automated reminders",
            "Last note. Our AI can also text past clients who haven't rebooked in a while, filling empty slots automatically",
        ],
    },
    "Dental": {
        "pain": "I know dental offices miss new patient calls during procedures and cleanings",
        "value": "answers every patient call 24/7, books appointments, and follows up on missed calls automatically",
        "followup_hooks": [
            "Following up. I was thinking about how many new patient calls {company_name} might lose during procedures",
            "Quick thought. A dental office here told me they added 12 new patients/month just by answering every call",
            "Last note. Our AI also handles after-hours calls and texts back anyone who called when you were closed",
        ],
    },
    "Mental Health": {
        "pain": "I know therapists and counsellors can't answer the phone during sessions, and clients rarely call back",
        "value": "answers every call while you're in session, handles intake questions, and books consultations automatically",
        "followup_hooks": [
            "Following up. I was thinking about how many potential clients call {company_name} during sessions and never call back",
            "Quick thought. A therapist here in Halifax told me she was losing 5+ new clients a month to missed calls",
            "Last note. Our AI handles the entire intake process by phone so new clients get booked without you lifting a finger",
        ],
    },
    "Cleaning": {
        "pain": "I know cleaning companies miss calls from potential clients when the team is out on jobs",
        "value": "answers every call, qualifies the lead, and books estimates into your calendar while you're out on jobs",
        "followup_hooks": [
            "Following up. I was thinking about how {company_name} handles new client calls when everyone's out cleaning",
            "Quick thought. A cleaning company owner told me he doubled his estimates just by answering every call",
            "Last note. Our AI can also follow up with past clients who haven't rebooked, bringing back recurring revenue",
        ],
    },
    "Automotive": {
        "pain": "I know auto shops miss calls when every mechanic is under a car",
        "value": "answers every call, books service appointments, and follows up on quotes that didn't convert",
        "followup_hooks": [
            "Following up. I was thinking about how many service calls {company_name} might miss during busy hours",
            "Quick thought. An auto shop owner here told me he was losing 5-10 service jobs a week just from missed calls",
            "Last note. Our AI can also follow up on quotes you've sent that haven't been accepted yet",
        ],
    },
    "Landscape": {
        "pain": "I know landscaping companies miss calls all day because the crew is always out on jobs",
        "value": "answers every call, qualifies the lead, and books estimates while you're out on site",
        "followup_hooks": [
            "Following up. Hard to answer calls when you're running crews all day, right?",
            "Quick thought. A landscaping company owner told me he was losing $10K/month in jobs from missed calls",
            "Last note. Our AI books estimates directly into your calendar so homeowners don't call the next company on Google",
        ],
    },
    "Elderly Care": {
        "pain": "I know elder care services get calls from families at all hours, especially during emergencies",
        "value": "answers every call 24/7, handles intake questions from families, and routes urgent calls immediately",
        "followup_hooks": [
            "Following up. Families looking for elder care often call after hours when they're stressed and need help fast",
            "Quick thought. An elder care provider told me 40% of new client calls came outside business hours",
            "Last note. Our AI gives families an immediate, compassionate response anytime they call",
        ],
    },
    "Retail": {
        "pain": "I know retail businesses get overwhelmed with customer calls about hours, inventory, and orders",
        "value": "handles all routine customer calls like hours, inventory checks, and order status so your team can focus on in-store customers",
        "followup_hooks": [
            "Following up. I was thinking about how many calls your team fields about basic stuff like store hours",
            "Quick thought. Our AI handles the routine calls so your staff can focus on the customers right in front of them",
        ],
    },
    "Repair Services": {
        "pain": "I know repair service companies miss calls when the team is out on emergency jobs",
        "value": "answers every call, triages urgency, and books service appointments while your crew is out on jobs",
        "followup_hooks": [
            "Following up. I was thinking about how {company_name} handles new service calls during emergencies",
            "Quick thought. A restoration company owner told me every missed call was a $5K-$15K job walking away",
        ],
    },
}

DEFAULT_HOOKS = {
    "pain": "I know local business owners miss calls and opportunities when they're busy running the business",
    "value": "answers every call 24/7, books appointments, and follows up with leads automatically",
    "followup_hooks": [
        "Following up. I was thinking about how many calls {company_name} might miss during your busiest hours",
        "Quick thought. A business owner here in Halifax told me he was losing clients just because no one could answer the phone",
        "Last note. Our AI handles everything by phone so you can focus on running {company_name}",
    ],
}


def generate_initial_email(owner):
    """Generate a fully custom initial email for an owner."""
    first = owner['first_name']
    company = owner['company_name']
    title = owner['title']
    industry = owner['industry']

    hooks = INDUSTRY_HOOKS.get(industry, DEFAULT_HOOKS)

    body = f"""Hi {first},

I'm Dylan, a student at Dalhousie University here in Halifax. I build custom AI voice agents for local businesses, and I already built one for {company}.

{hooks['pain']}. The agent I made for you {hooks['value']}.

Let me know what days work for a call.

Cheers,
Dylan"""

    # Custom subject using their name
    subjects = [
        f"Quick idea for {company}, {first}",
        f"{first}, Dal student with something for {company}",
        f"For {first} at {company}",
        f"{first}, quick question about {company}",
    ]
    subject = random.choice(subjects)

    return subject, body


def generate_followups(owner):
    """Generate 3 follow-up emails."""
    first = owner['first_name']
    company = owner['company_name']
    industry = owner['industry']

    hooks = INDUSTRY_HOOKS.get(industry, DEFAULT_HOOKS)
    followup_hooks = hooks.get('followup_hooks', DEFAULT_HOOKS['followup_hooks'])

    followups = []

    # Follow-up 1 (Day 3)
    hook1 = followup_hooks[0].format(company_name=company) if len(followup_hooks) > 0 else f"Following up on my note about {company}"
    f1_body = f"""Hi {first},

{hook1}. Wanted to bump this up in case it got buried.

We already built a custom agent for {company} that {hooks['value']}. Let me know what days work for a quick call.

Dylan"""
    followups.append(("", f1_body))  # Empty subject = reply to original thread

    # Follow-up 2 (Day 5)
    hook2 = followup_hooks[1].format(company_name=company) if len(followup_hooks) > 1 else f"Thought of {company} again"
    f2_body = f"""Hi {first},

{hook2}.

Would a quick call be worth 10 minutes of your time? Let me know what days work.

Dylan"""
    followups.append(("", f2_body))

    # Follow-up 3 (Day 8) - breakup email
    f3_body = f"""Hi {first},

I'll keep this short. I've reached out a few times about an AI phone agent for {company}. If the timing isn't right, totally understand.

If you ever want to see how it works, just let me know what days work for a call.

All the best with {company},
Dylan"""
    followups.append(("", f3_body))

    return followups


def main():
    print("=== Owner Campaign Generator (Fully Custom + Follow-ups) ===\n")

    # Load enriched owners
    leads = []
    with open(INPUT_FILE, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get('email', '').strip():
                leads.append(row)

    print(f"Loaded {len(leads)} owners with emails")

    # Generate emails
    results = []
    for owner in leads:
        # Initial email
        subject, body = generate_initial_email(owner)
        results.append({
            'email': owner['email'],
            'first_name': owner['first_name'],
            'last_name': owner['last_name'],
            'company_name': owner['company_name'],
            'title': owner['title'],
            'industry': owner['industry'],
            'sequence_step': 1,
            'delay_days': 0,
            'subject': subject,
            'body': body,
        })

        # Follow-ups
        followups = generate_followups(owner)
        delays = [3, 5, 8]
        for i, (fu_subject, fu_body) in enumerate(followups):
            results.append({
                'email': owner['email'],
                'first_name': owner['first_name'],
                'last_name': owner['last_name'],
                'company_name': owner['company_name'],
                'title': owner['title'],
                'industry': owner['industry'],
                'sequence_step': i + 2,
                'delay_days': delays[i],
                'subject': fu_subject,
                'body': fu_body,
            })

    # Write output
    fieldnames = ['email', 'first_name', 'last_name', 'company_name', 'title',
                  'industry', 'sequence_step', 'delay_days', 'subject', 'body']
    with open(OUTPUT_FILE, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    owners_count = len(leads)
    print(f"Generated {len(results)} emails ({owners_count} owners x 4 steps)")
    print(f"Saved to {OUTPUT_FILE}")

    # Show sample
    print("\n--- Sample (first owner) ---")
    for r in results[:4]:
        print(f"\nStep {r['sequence_step']} (Day +{r['delay_days']}):")
        if r['subject']:
            print(f"SUBJECT: {r['subject']}")
        print(f"BODY:\n{r['body']}")
        print("-" * 40)


if __name__ == '__main__':
    main()
