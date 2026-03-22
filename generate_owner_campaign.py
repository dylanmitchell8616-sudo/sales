#!/usr/bin/env python3
"""
Generate fully custom emails + follow-ups for business owners.
Each email is unique per owner, references their name, title, company, and industry.

Now loads industry-specific templates from campaign_templates.json for pain points,
tone, CTA style, and personalization depth. Falls back to built-in defaults if no
template file is found or no vertical matches.
"""

import csv
import json
import os
import random

INPUT_FILE = "output/halifax_owners_enriched.csv"
OUTPUT_FILE = "output/owner_campaign_emails.csv"
TEMPLATES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "campaign_templates.json")


# ---------------------------------------------------------------------------
# Campaign template loading
# ---------------------------------------------------------------------------

def load_campaign_templates(filepath: str = TEMPLATES_FILE) -> dict:
    """Load campaign templates from JSON file."""
    if not os.path.exists(filepath):
        print(f"Warning: Campaign templates file '{filepath}' not found, using built-in defaults")
        return {}
    with open(filepath, encoding="utf-8") as f:
        return json.load(f)


def detect_vertical(industry: str, company_name: str, templates: dict) -> tuple:
    """Auto-detect the best matching vertical from campaign_templates.json.

    Checks the lead's industry (and company name as fallback) against each
    vertical's aliases list. Returns (vertical_key, vertical_config) or
    (None, None) if no match is found.
    """
    verticals = templates.get("verticals", {})
    if not verticals:
        return None, None

    # Normalize search terms
    search_text = f"{industry} {company_name}".lower()

    for vertical_key, vertical_config in verticals.items():
        aliases = vertical_config.get("aliases", [])
        for alias in aliases:
            if alias.lower() in search_text:
                return vertical_key, vertical_config

    return None, None


def build_hooks_from_template(vertical: dict) -> dict:
    """Convert a campaign_templates.json vertical config into the hooks format
    used by the email generator (pain, value, followup_hooks)."""
    pain_points = vertical.get("pain_points", [])
    value_props = vertical.get("value_props", [])
    followup_hooks_raw = vertical.get("followup_hooks", [])

    # Pick the first pain point as the primary pain statement
    pain = pain_points[0] if pain_points else "local business owners miss calls and opportunities when they're busy running the business"
    # Make it conversational: "I know [pain]"
    if not pain.lower().startswith("i know"):
        pain = f"I know {pain[0].lower()}{pain[1:]}"

    # Pick the first value prop
    value = value_props[0] if value_props else "answers every call 24/7, books appointments, and follows up with leads automatically"
    # Strip leading "AI receptionist/agent" prefix for flow after "The agent I made for you..."
    value_lower = value.lower()
    for prefix in ["ai receptionist ", "ai outbound agent ", "ai agent ", "ai "]:
        if value_lower.startswith(prefix):
            value = value[len(prefix):]
            break

    return {
        "pain": pain,
        "value": value,
        "followup_hooks": followup_hooks_raw if followup_hooks_raw else [
            "Following up. I was thinking about how many calls {company_name} might miss during your busiest hours",
            "Quick thought. A business owner told me he was losing clients just because no one could answer the phone",
            "Last note. Our AI handles everything by phone so you can focus on running {company_name}",
        ],
    }


def get_template_settings(vertical: dict | None, templates: dict) -> dict:
    """Extract tone, CTA style, email length, and followup cadence from a vertical
    config, falling back to global defaults."""
    defaults = templates.get("global_defaults", {})
    if vertical is None:
        return {
            "tone": defaults.get("tone", "friendly"),
            "cta_style": defaults.get("cta_style", "soft_ask"),
            "email_length": defaults.get("email_length", "short"),
            "followup_cadence_days": defaults.get("followup_cadence_days", [3, 5, 8]),
            "personalization_depth": defaults.get("personalization_depth", "medium"),
            "subject_line_angles": [],
            "proof_points": [],
        }
    return {
        "tone": vertical.get("tone", defaults.get("tone", "friendly")),
        "cta_style": vertical.get("cta_style", defaults.get("cta_style", "soft_ask")),
        "email_length": vertical.get("email_length", defaults.get("email_length", "short")),
        "followup_cadence_days": vertical.get("followup_cadence_days", defaults.get("followup_cadence_days", [3, 5, 8])),
        "personalization_depth": vertical.get("personalization_depth", defaults.get("personalization_depth", "medium")),
        "subject_line_angles": vertical.get("subject_line_angles", []),
        "proof_points": vertical.get("proof_points", []),
    }


# Load templates at module level
_CAMPAIGN_TEMPLATES = load_campaign_templates()


# ---------------------------------------------------------------------------
# Legacy industry hooks (used as fallback when no template match)
# ---------------------------------------------------------------------------

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


def get_hooks_for_owner(owner: dict) -> tuple:
    """Get the best hooks for an owner, preferring campaign_templates.json verticals
    over legacy INDUSTRY_HOOKS, with DEFAULT_HOOKS as final fallback.

    Returns (hooks_dict, template_settings_dict).
    """
    industry = owner.get('industry', '')
    company = owner.get('company_name', '')

    # Try campaign_templates.json first
    vertical_key, vertical_config = detect_vertical(industry, company, _CAMPAIGN_TEMPLATES)
    if vertical_config is not None:
        hooks = build_hooks_from_template(vertical_config)
        settings = get_template_settings(vertical_config, _CAMPAIGN_TEMPLATES)
        return hooks, settings

    # Fall back to legacy INDUSTRY_HOOKS
    if industry in INDUSTRY_HOOKS:
        hooks = INDUSTRY_HOOKS[industry]
        settings = get_template_settings(None, _CAMPAIGN_TEMPLATES)
        return hooks, settings

    # Final fallback
    return DEFAULT_HOOKS, get_template_settings(None, _CAMPAIGN_TEMPLATES)


def generate_initial_email(owner):
    """Generate a fully custom initial email for an owner.
    Uses campaign_templates.json for industry-aware tone, CTA, and pain points."""
    first = owner['first_name']
    company = owner['company_name']
    title = owner['title']
    industry = owner['industry']

    hooks, settings = get_hooks_for_owner(owner)

    # Build CTA based on template settings
    cta_style = settings.get("cta_style", "soft_ask")
    if cta_style == "direct_ask":
        cta_line = "Let me know what days work for a call."
    elif cta_style == "curiosity_driven":
        cta_line = f"I built a custom demo for {company}. Want to see it? Let me know what days work for a call."
    else:  # soft_ask
        cta_line = "Would a quick 10-minute call be worth your time to see how it works?"

    body = f"""Hi {first},

I'm Dylan, I build custom AI voice agents for local businesses, and I already built one for {company}.

{hooks['pain']}. The agent I made for you {hooks['value']}.

{cta_line}

Cheers,
Dylan"""

    # Use template subject lines if available, otherwise fall back to defaults
    subject_angles = settings.get("subject_line_angles", [])
    if subject_angles:
        subject = random.choice(subject_angles).format(
            company=company, first_name=first, first=first
        )
    else:
        subjects = [
            f"Quick idea for {company}, {first}",
            f"{first}, I built something for {company}",
            f"For {first} at {company}",
            f"{first}, quick question about {company}",
        ]
        subject = random.choice(subjects)

    return subject, body


def generate_followups(owner):
    """Generate 3 follow-up emails using template-aware hooks and cadence."""
    first = owner['first_name']
    company = owner['company_name']
    industry = owner['industry']

    hooks, settings = get_hooks_for_owner(owner)
    followup_hooks = hooks.get('followup_hooks', DEFAULT_HOOKS['followup_hooks'])
    proof_points = settings.get('proof_points', [])

    followups = []

    # Follow-up 1
    hook1 = followup_hooks[0].format(company_name=company, company=company) if len(followup_hooks) > 0 else f"Following up on my note about {company}"
    f1_body = f"""Hi {first},

{hook1}. Wanted to bump this up in case it got buried.

We already built a custom agent for {company} that {hooks['value']}. Let me know what days work for a quick call.

Dylan"""
    followups.append(("", f1_body))

    # Follow-up 2 (use proof point from template if available)
    if len(followup_hooks) > 1:
        hook2 = followup_hooks[1].format(company_name=company, company=company)
    elif proof_points:
        hook2 = random.choice(proof_points)
    else:
        hook2 = f"Thought of {company} again"
    f2_body = f"""Hi {first},

{hook2}.

Would a quick call be worth 10 minutes of your time? Let me know what days work.

Dylan"""
    followups.append(("", f2_body))

    # Follow-up 3 - breakup email
    if len(followup_hooks) > 2:
        hook3 = followup_hooks[2].format(company_name=company, company=company)
        f3_body = f"""Hi {first},

I'll keep this short. {hook3}

If the timing isn't right, totally understand. If you ever want to see how it works, just let me know.

All the best with {company},
Dylan"""
    else:
        f3_body = f"""Hi {first},

I'll keep this short. I've reached out a few times about an AI phone agent for {company}. If the timing isn't right, totally understand.

If you ever want to see how it works, just let me know what days work for a call.

All the best with {company},
Dylan"""
    followups.append(("", f3_body))

    return followups


def main():
    print("=== Owner Campaign Generator (Fully Custom + Follow-ups) ===\n")

    # Report template status
    if _CAMPAIGN_TEMPLATES:
        verticals = _CAMPAIGN_TEMPLATES.get("verticals", {})
        print(f"Loaded campaign templates with {len(verticals)} verticals: {', '.join(verticals.keys())}")
    else:
        print("No campaign templates loaded, using built-in industry hooks only")

    # Load enriched owners
    leads = []
    with open(INPUT_FILE, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get('email', '').strip():
                leads.append(row)

    print(f"Loaded {len(leads)} owners with emails")

    # Track which verticals were matched
    vertical_matches = {}

    # Generate emails
    results = []
    for owner in leads:
        # Detect vertical for reporting
        industry = owner.get('industry', '')
        company = owner.get('company_name', '')
        vkey, _ = detect_vertical(industry, company, _CAMPAIGN_TEMPLATES)
        match_label = vkey or industry or "generic"
        vertical_matches[match_label] = vertical_matches.get(match_label, 0) + 1

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

        # Follow-ups with template-aware cadence
        followups = generate_followups(owner)
        _, settings = get_hooks_for_owner(owner)
        delays = settings.get('followup_cadence_days', [3, 5, 8])
        for i, (fu_subject, fu_body) in enumerate(followups):
            delay = delays[i] if i < len(delays) else delays[-1] + (i - len(delays) + 1) * 2
            results.append({
                'email': owner['email'],
                'first_name': owner['first_name'],
                'last_name': owner['last_name'],
                'company_name': owner['company_name'],
                'title': owner['title'],
                'industry': owner['industry'],
                'sequence_step': i + 2,
                'delay_days': delay,
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
    print(f"\nGenerated {len(results)} emails ({owners_count} owners x 4 steps)")
    print(f"Saved to {OUTPUT_FILE}")

    # Report vertical distribution
    print("\n--- Vertical Distribution ---")
    for label, count in sorted(vertical_matches.items(), key=lambda x: -x[1]):
        print(f"  {label}: {count} owners")

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
