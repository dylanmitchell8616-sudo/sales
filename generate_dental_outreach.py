#!/usr/bin/env python3
"""
Generate dental DSO outreach CSV with personalized emails for all 65 Clay leads.
Includes initial email + 2 follow-ups per contact, each with a unique angle.
Run once to produce output/dental_dso_outreach.csv.
"""
import csv
import os

CALENDAR = "https://calendly.com/realsideai"
OUTPUT = "output/dental_dso_outreach.csv"


# ---------------------------------------------------------------------------
# Initial email templates (Email 1)
# ---------------------------------------------------------------------------

def ceo_email_1(first, company):
    return {
        "subject": "The call every new patient makes before choosing a dentist",
        "body": f"""Hi {first},

Most dental CEOs I talk to are surprised by this number: 18% of inbound calls at multi-location groups go unanswered during peak hours.

At {company}'s scale, that's hundreds of new patients per week choosing the office down the street instead.

Realside AI puts an AI Receptionist on every phone line. Answers 24/7, books instantly, handles FAQs. No staffing headaches, no dropped calls.

DSOs in our network see 25% more bookings within 60 days.

Worth 15 minutes? {CALENDAR}

Dylan"""
    }


def vp_ops_email_1(first, company):
    return {
        "subject": "What's your per-location call abandonment rate?",
        "body": f"""Hi {first},

One location missing 20% of inbound calls loses roughly $12K a month in new patient revenue.

Multiply that across {company}'s footprint and you're looking at a significant recurring leak.

Realside AI deploys an AI Receptionist across every location. Every call answered 24/7, every appointment booked automatically, every FAQ handled consistently. Zero training costs. Zero turnover.

DSOs we work with recover 20 to 30% of previously missed calls within 60 days.

Would love to show you the numbers. {CALENDAR}

Dylan"""
    }


def regional_mgr_email_1(first, company):
    return {
        "subject": "Your front desk is turning new patients away right now",
        "body": f"""Hi {first},

You already know the problem. Peak hours flood the front desk, calls go to voicemail, and new patients hang up and call the next office on the list.

Realside AI's AI Receptionist answers every call instantly. Books appointments, handles FAQs, and does live transfers across every location in your region.

Practices we work with see 25% more bookings within 60 days without adding a single headcount.

Got 15 minutes to see how it works? {CALENDAR}

Dylan"""
    }


def cx_email_1(first, company):
    return {
        "subject": "The patient experience starts before they walk in the door",
        "body": f"""Hi {first},

At {company}'s scale, thousands of patient relationships begin with a phone call. That first impression is being shaped by whoever happens to be at the front desk that day.

Realside AI standardizes that moment. Every call answered instantly, professionally, and consistently across all locations, 24/7.

Patient satisfaction scores and booking rates both jump within 60 days.

Would love to show you a demo. {CALENDAR}

Dylan"""
    }


def digital_email_1(first, company):
    return {
        "subject": "AI that pays for itself in 60 days",
        "body": f"""Hi {first},

Realside AI builds AI Employees specifically for multi-location dental groups.

The AI Inbound Receptionist answers every call 24/7 and books appointments. The AI Outbound Agent calls new leads in under 2 minutes and reactivates dormant patients.

At {company}'s scale, recovering even 5% of missed calls across hundreds of locations adds millions annually.

Easy API integration. Live in days. ROI visible in month one.

Worth 15 minutes? {CALENDAR}

Dylan"""
    }


def growth_email_1(first, company):
    return {
        "subject": "The lowest-hanging revenue at {company}".format(company=company),
        "body": f"""Hi {first},

If {company} is focused on growth, here is the fastest lever: the calls your front desks cannot answer.

Most dental groups miss 15 to 25% of inbound calls during peak hours. That is revenue walking directly to a competitor.

Realside AI's AI Receptionist answers every call 24/7, books appointments, and never misses a new patient. We see 25% booking increases within 60 days.

Open to a quick demo? {CALENDAR}

Dylan"""
    }


# ---------------------------------------------------------------------------
# Follow-up 1 templates (Email 2, ~3 days later)
# ---------------------------------------------------------------------------

def ceo_followup_1(first, company):
    return {
        "subject": "One number that might surprise you",
        "body": f"""Hi {first},

Quick follow-up.

One stat that comes up a lot with DSO leaders: dental practices that deploy AI call answering see an average $8,400 increase in monthly revenue per location within 90 days.

For {company}, that math gets interesting fast.

I can walk you through exactly how it works in 15 minutes. {CALENDAR}

Dylan"""
    }


def vp_ops_followup_1(first, company):
    return {
        "subject": "The staffing problem that never goes away",
        "body": f"""Hi {first},

Wanted to follow up with a different angle.

Front desk turnover averages 35% annually in dental. Every time someone leaves, you lose booked appointments, consistency, and training investment.

Realside AI removes that variable entirely. The AI handles every inbound call the same way, every time, across every {company} location.

Happy to show you how other DSOs have solved this. {CALENDAR}

Dylan"""
    }


def regional_mgr_followup_1(first, company):
    return {
        "subject": "What 25% more bookings looks like per location",
        "body": f"""Hi {first},

Following up from last week.

One of the regional managers we work with added 47 net-new appointments per location in the first month. No new hires. Just AI answering every call that used to go to voicemail.

Happy to share the specifics on a short call. {CALENDAR}

Dylan"""
    }


def cx_followup_1(first, company):
    return {
        "subject": "What patients say when they can always get through",
        "body": f"""Hi {first},

One thing I keep hearing from CX leaders we work with: the biggest driver of patient satisfaction scores is simply being able to reach someone.

Realside AI ensures every {company} patient reaches a professional, helpful voice on the first try, 24/7, with zero hold time.

Would love to show you what that looks like in practice. {CALENDAR}

Dylan"""
    }


def digital_followup_1(first, company):
    return {
        "subject": "Integration takes less than a week",
        "body": f"""Hi {first},

One common concern I hear is that deploying AI sounds complicated.

Realside AI integrates with your existing phone system and practice management software via API. Most {company} locations can be live within 5 business days. No hardware, no disruption to current workflows.

Happy to walk through the technical setup. {CALENDAR}

Dylan"""
    }


def growth_followup_1(first, company):
    return {
        "subject": "Your competitors are already doing this",
        "body": f"""Hi {first},

Quick note.

Three of the top 10 DSOs in the country are now running AI phone answering across their networks. The ones doing it first are locking in new patients that the slower-moving groups are losing.

{company} is in a strong position to move on this before it becomes table stakes.

Worth a 15-minute look? {CALENDAR}

Dylan"""
    }


# ---------------------------------------------------------------------------
# Follow-up 2 templates (Email 3, ~6 days later)
# ---------------------------------------------------------------------------

def ceo_followup_2(first, company):
    return {
        "subject": "Last note from me",
        "body": f"""Hi {first},

I know your inbox is full so I'll keep this short.

We help DSOs like {company} recover missed calls and add 20 to 30% more bookings without adding headcount. If the timing is not right, no worries at all.

But if you have 15 minutes in the next couple weeks, I think the ROI conversation will be worth it. {CALENDAR}

Dylan"""
    }


def vp_ops_followup_2(first, company):
    return {
        "subject": "One last thought before I go quiet",
        "body": f"""Hi {first},

Last follow-up, I promise.

If {company} is dealing with any of these: inconsistent call handling across locations, front desk overflow during peak hours, or missed new patient calls — we have a direct solution.

Happy to show you a 15-minute demo whenever makes sense. {CALENDAR}

Dylan"""
    }


def regional_mgr_followup_2(first, company):
    return {
        "subject": "Closing the loop",
        "body": f"""Hi {first},

Just closing the loop on my previous notes.

If adding 20 to 30% more bookings per location without hiring is on your radar, I'd love to show you how Realside AI makes that happen.

If the timing is off, no worries at all. {CALENDAR}

Dylan"""
    }


def cx_followup_2(first, company):
    return {
        "subject": "Final note",
        "body": f"""Hi {first},

Last note from me.

Patient experience and call answer rates are directly connected. If improving first-contact consistency across {company} is a priority this year, Realside AI is worth 15 minutes.

{CALENDAR}

Dylan"""
    }


def digital_followup_2(first, company):
    return {
        "subject": "Leaving this here",
        "body": f"""Hi {first},

One last note.

If {company} is evaluating AI tools this year, Realside AI is the only solution built specifically for multi-location dental and med spa groups. Not a generic chatbot. Purpose-built AI Employees.

Happy to do a quick walkthrough whenever. {CALENDAR}

Dylan"""
    }


def growth_followup_2(first, company):
    return {
        "subject": "Last one, I promise",
        "body": f"""Hi {first},

Last message.

If growth is on the agenda for {company} and you want to see how other DSOs are adding 25% more bookings without new hires, I can show you in 15 minutes.

{CALENDAR}

Dylan"""
    }


# ---------------------------------------------------------------------------
# Template maps
# ---------------------------------------------------------------------------

TEMPLATE_FNS = {
    "ceo":      (ceo_email_1,       ceo_followup_1,       ceo_followup_2),
    "vp_ops":   (vp_ops_email_1,    vp_ops_followup_1,    vp_ops_followup_2),
    "regional": (regional_mgr_email_1, regional_mgr_followup_1, regional_mgr_followup_2),
    "cx":       (cx_email_1,        cx_followup_1,        cx_followup_2),
    "digital":  (digital_email_1,   digital_followup_1,   digital_followup_2),
    "growth":   (growth_email_1,    growth_followup_1,    growth_followup_2),
}

# ---------------------------------------------------------------------------
# All 65 contacts
# ---------------------------------------------------------------------------

CONTACTS = [
    # 1 contact per company — owner/CEO only
    ("Pat Bauer",         "pat.bauer@heartland.com",         "Heartland Dental",     "heartland.com",           "President and CEO",             "ceo"),
    ("Bob Fontana",       "bob.fontana@aspendental.com",     "Aspen Dental",         "aspendental.com",         "Chairman and CEO",              "ceo"),
    ("Richard Ashton",    "richard.ashton@pacificdentalservices.com", "PDS Health",   "pacificdentalservices.com", "Multi-Practice Owner Dentist", "ceo"),
    ("Laurence Benz",     "laurence.benz@dentalcarealliance.com", "Dental Care Alliance", "dentalcarealliance.com", "CEO",                        "ceo"),
    ("Peter Bridgman",    "peter.bridgman@affordablecare.com", "Affordable Care",    "affordablecare.com",      "CEO",                           "ceo"),
]


def main():
    os.makedirs("output", exist_ok=True)
    fieldnames = [
        "contact_name", "contact_email", "company_name", "domain",
        "contact_title",
        "subject", "body",
        "followup1_subject", "followup1_body",
        "followup2_subject", "followup2_body",
    ]

    rows_written = 0
    with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for name, email, company, domain, title, template_key in CONTACTS:
            first = name.split()[0]
            email_fn, fu1_fn, fu2_fn = TEMPLATE_FNS[template_key]

            e1 = email_fn(first, company)
            e2 = fu1_fn(first, company)
            e3 = fu2_fn(first, company)

            writer.writerow({
                "contact_name":       name,
                "contact_email":      email,
                "company_name":       company,
                "domain":             domain,
                "contact_title":      title,
                "subject":            e1["subject"],
                "body":               e1["body"],
                "followup1_subject":  e2["subject"],
                "followup1_body":     e2["body"],
                "followup2_subject":  e3["subject"],
                "followup2_body":     e3["body"],
            })
            rows_written += 1

    print(f"Generated {rows_written} contacts (3 emails each = {rows_written * 3} total) -> {OUTPUT}")


if __name__ == "__main__":
    main()
