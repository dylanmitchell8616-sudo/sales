#!/usr/bin/env python3
"""
Generate dental DSO outreach CSV with personalized emails for all 63 Clay leads.
Run once to produce output/dental_dso_outreach.csv.
"""
import csv
import os

CALENDAR = "https://calendly.com/realsideai"
OUTPUT = "output/dental_dso_outreach.csv"

# Role-based email templates
def ceo_email(first, company):
    return {
        "subject": "The call every new patient makes before choosing a dentist",
        "body": f"""Hi {first},

With {company}'s scale, even a 10% improvement in call-to-booking conversion represents millions in recovered revenue across hundreds of locations.

Realside AI puts an AI Inbound Receptionist on every phone line. It answers 24/7, books instantly, and handles FAQs. No staffing headaches. No dropped calls. No missed new patients.

We're helping multi-location dental groups add 20-30% more bookings without adding headcount.

Worth 15 minutes? {CALENDAR}

Dylan"""
    }

def vp_ops_email(first, company):
    return {
        "subject": "What's your per-location call abandonment rate?",
        "body": f"""Hi {first},

At {company}'s scale, front desk inconsistency is expensive. One location missing 20% of inbound calls loses roughly $10-15K/month in appointments.

Realside AI deploys an AI Receptionist across every location. It answers every call 24/7, books instantly, and handles FAQs consistently. No training costs. No turnover.

DSOs in our network recover 20-30% of previously lost calls within 60 days.

Would love to show you the numbers. {CALENDAR}

Dylan"""
    }

def regional_mgr_email(first, company):
    return {
        "subject": "Your front desk is turning new patients away",
        "body": f"""Hi {first},

Managing multiple practices means you know the problem. Peak hours flood the front desk, calls go to voicemail, and new patients hang up and call the office down the street.

Realside AI's AI Receptionist answers every call instantly. It books appointments, answers FAQs, and does live transfers across every location in your region automatically.

Practices we work with see 25%+ more bookings within 60 days.

Got 15 minutes to see how it works? {CALENDAR}

Dylan"""
    }

def cx_email(first, company):
    return {
        "subject": "The first patient touchpoint is a phone call",
        "body": f"""Hi {first},

The patient experience starts before they walk through the door. It starts with the phone call. At {company}'s scale that's thousands of calls per day being fielded by varying front desk teams.

Realside AI standardizes that first touchpoint. Every call is answered instantly, professionally, and consistently, 24/7, across all locations.

Patient satisfaction and booking rates both jump within 60 days.

Would love to show you a demo. {CALENDAR}

Dylan"""
    }

def digital_email(first, company):
    return {
        "subject": "AI that pays for itself in 60 days",
        "body": f"""Hi {first},

Realside AI builds AI Employees specifically for multi-location dental groups. The AI Inbound Receptionist answers every call 24/7 and books appointments. The AI Outbound Agent calls new leads in under 2 minutes and reactivates dormant patients.

At {company}'s scale, recovering 5% of missed calls across hundreds of locations is transformational.

Easy API integration. Deployed in days. ROI visible in the first month.

Worth 15 minutes? {CALENDAR}

Dylan"""
    }

def growth_email(first, company):
    return {
        "subject": "Adding 25% more bookings without adding headcount",
        "body": f"""Hi {first},

If {company} is focused on growth, here is the lowest-hanging fruit: the calls your front desks can't answer.

Most dental offices miss 15-25% of inbound calls during peak hours. That's revenue walking to a competitor.

Realside AI's AI Receptionist answers every call 24/7. It books appointments, handles FAQs, and never misses a new patient. We're seeing 25%+ booking increases across multi-location groups within 60 days.

Open to a quick demo? {CALENDAR}

Dylan"""
    }

# All 63 contacts with role → template mapping
CONTACTS = [
    # Heartland Dental
    ("Pat Bauer", "pat.bauer@heartland.com", "Heartland Dental", "heartland.com", "President and CEO", "ceo"),
    ("Jamie Gallo", "jamie.gallo@heartland.com", "Heartland Dental", "heartland.com", "SVP Marketing", "growth"),
    ("Lydia Wagner", "lydia.wagner@heartland.com", "Heartland Dental", "heartland.com", "Senior Director of Marketing", "growth"),
    ("Melissa Malloy", "melissa.malloy@heartland.com", "Heartland Dental", "heartland.com", "VP of Operations", "vp_ops"),
    ("Robert Mongrain", "robert.mongrain@heartland.com", "Heartland Dental", "heartland.com", "Director of Clinical Advocacy", "digital"),
    ("Kenneth Jones", "kenneth.jones@heartland.com", "Heartland Dental", "heartland.com", "Director of Facilities", "vp_ops"),
    ("Luis Mata", "luis.mata@heartland.com", "Heartland Dental", "heartland.com", "VP Operations, Education and Support", "vp_ops"),
    ("Monique Bell", "monique.bell@heartland.com", "Heartland Dental", "heartland.com", "Vice President Operations", "vp_ops"),
    ("Jeremy Stroud", "jeremy.stroud@heartland.com", "Heartland Dental", "heartland.com", "VP, Customer Service", "cx"),
    ("Stacey Smith", "stacey.smith@heartland.com", "Heartland Dental", "heartland.com", "Director, Doctor Recruiting", "regional"),
    ("Alicia Barker", "alicia.barker@heartland.com", "Heartland Dental", "heartland.com", "Sr Director of Operations", "vp_ops"),
    ("Tim Larson", "tim.larson@heartland.com", "Heartland Dental", "heartland.com", "Clinical Director of Laser Dentistry", "regional"),
    ("Robert Jerome", "robert.jerome@heartland.com", "Heartland Dental", "heartland.com", "SVP, Chief Digital Officer", "digital"),
    ("Stephanie Townsend", "stephanie.townsend@heartland.com", "Heartland Dental", "heartland.com", "SVP of Operations", "vp_ops"),
    ("Trish Knott", "trish.knott@heartland.com", "Heartland Dental", "heartland.com", "Manager of Operations", "regional"),
    ("Jeff Ungrund", "jeff.ungrund@heartland.com", "Heartland Dental", "heartland.com", "VP of Affiliations", "vp_ops"),
    ("Jennifer Pronobis", "jennifer.pronobis@heartland.com", "Heartland Dental", "heartland.com", "Regional Director of Operations", "regional"),

    # Aspen Dental
    ("Bob Fontana", "bob.fontana@aspendental.com", "Aspen Dental", "aspendental.com", "Chairman and CEO", "ceo"),
    ("Robert Lowe", "robert.lowe@aspendental.com", "Aspen Dental", "aspendental.com", "Managing Clinical Director", "digital"),
    ("Kimberly Jones", "kimberly.jones@aspendental.com", "Aspen Dental", "aspendental.com", "VP of Hygiene Operations", "vp_ops"),
    ("Shawn McGarvey", "shawn.mcgarvey@aspendental.com", "Aspen Dental", "aspendental.com", "Division VP of Operations", "vp_ops"),
    ("Tiffany Biddlecome", "tiffany.biddlecome@aspendental.com", "Aspen Dental", "aspendental.com", "Regional Manager", "regional"),
    ("Scott Kertenis", "scott.kertenis@aspendental.com", "Aspen Dental", "aspendental.com", "SVP Service Line Operations", "vp_ops"),
    ("Jessica Hennecke", "jessica.hennecke@aspendental.com", "Aspen Dental", "aspendental.com", "VP, Lab Implementation & Digital Dentistry", "digital"),
    ("Nathan Taylor", "nathan.taylor@aspendental.com", "Aspen Dental", "aspendental.com", "Dentist Owner", "regional"),
    ("Jason Elkhouri", "jason.elkhouri@aspendental.com", "Aspen Dental", "aspendental.com", "Senior Director of Operations", "vp_ops"),
    ("Meghan Neumeister", "meghan.neumeister@aspendental.com", "Aspen Dental", "aspendental.com", "Operations Manager", "regional"),
    ("Dee Butkiewicz", "dee.butkiewicz@aspendental.com", "Aspen Dental", "aspendental.com", "Director of Operations", "vp_ops"),
    ("Tammy Christian", "tammy.christian@aspendental.com", "Aspen Dental", "aspendental.com", "Territory Director", "regional"),

    # PDS Health
    ("Nicole Warn", "nicole.warn@pacificdentalservices.com", "PDS Health", "pacificdentalservices.com", "Operations Manager", "regional"),
    ("Richard Ashton", "richard.ashton@pacificdentalservices.com", "PDS Health", "pacificdentalservices.com", "Multi-Practice Owner Dentist", "ceo"),
    ("Heather Kain", "heather.kain@pacificdentalservices.com", "PDS Health", "pacificdentalservices.com", "Regional Manager", "regional"),
    ("Sue Rudow", "sue.rudow@pacificdentalservices.com", "PDS Health", "pacificdentalservices.com", "Regional Manager", "regional"),
    ("Marta Brocka", "marta.brocka@pacificdentalservices.com", "PDS Health", "pacificdentalservices.com", "Regional Manager", "regional"),
    ("Athena Burkholder", "athena.burkholder@pacificdentalservices.com", "PDS Health", "pacificdentalservices.com", "Operations Manager", "regional"),
    ("Adam Godoy", "adam.godoy@pacificdentalservices.com", "PDS Health", "pacificdentalservices.com", "Regional Manager", "regional"),
    ("Erin Ortega", "erin.ortega@pacificdentalservices.com", "PDS Health", "pacificdentalservices.com", "Regional Partner", "regional"),
    ("Matthew Rich", "matthew.rich@pacificdentalservices.com", "PDS Health", "pacificdentalservices.com", "Regional Manager", "regional"),
    ("Alisha Taylor", "alisha.taylor@pacificdentalservices.com", "PDS Health", "pacificdentalservices.com", "Specialty Regional Manager", "regional"),
    ("Adam Morris", "adam.morris@pacificdentalservices.com", "PDS Health", "pacificdentalservices.com", "Regional Manager", "regional"),
    ("Katie Bezler", "katie.bezler@pacificdentalservices.com", "PDS Health", "pacificdentalservices.com", "Regional Manager", "regional"),
    ("Amber Outlaw", "amber.outlaw@pacificdentalservices.com", "PDS Health", "pacificdentalservices.com", "Operations Manager", "regional"),
    ("Jason Wisdom", "jason.wisdom@pacificdentalservices.com", "PDS Health", "pacificdentalservices.com", "Operations Manager II", "regional"),
    ("Baraka Harper", "baraka.harper@pacificdentalservices.com", "PDS Health", "pacificdentalservices.com", "Specialty Regional Manager", "regional"),
    ("Reggie Oronoz", "reggie.oronoz@pacificdentalservices.com", "PDS Health", "pacificdentalservices.com", "Operations Manager", "regional"),
    ("Debbie Day", "debbie.day@pacificdentalservices.com", "PDS Health", "pacificdentalservices.com", "Operations Manager", "regional"),

    # Dental Care Alliance
    ("Laurence Benz", "laurence.benz@dentalcarealliance.com", "Dental Care Alliance", "dentalcarealliance.com", "CEO", "ceo"),
    ("Clayton Russell", "clayton.russell@dentalcarealliance.com", "Dental Care Alliance", "dentalcarealliance.com", "VP of Operational Strategy", "vp_ops"),
    ("Hadiya Peele", "hadiya.peele@dentalcarealliance.com", "Dental Care Alliance", "dentalcarealliance.com", "Director of Operations", "vp_ops"),
    ("Trey Mueller", "trey.mueller@dentalcarealliance.com", "Dental Care Alliance", "dentalcarealliance.com", "Chief Clinical Officer", "digital"),
    ("Beth Wynacht", "beth.wynacht@dentalcarealliance.com", "Dental Care Alliance", "dentalcarealliance.com", "VP of Integrations", "digital"),
    ("Colleen McFarlin", "colleen.mcfarlin@dentalcarealliance.com", "Dental Care Alliance", "dentalcarealliance.com", "Director of Growth", "growth"),
    ("Jared Duley", "jared.duley@dentalcarealliance.com", "Dental Care Alliance", "dentalcarealliance.com", "VP, Customer Experience", "cx"),
    ("Alok Jain", "alok.jain@dentalcarealliance.com", "Dental Care Alliance", "dentalcarealliance.com", "Sr. Director - Patient Relationship Management", "cx"),
    ("Julie Soczka", "julie.soczka@dentalcarealliance.com", "Dental Care Alliance", "dentalcarealliance.com", "Senior Director/VP Strategic Initiatives", "growth"),

    # Affordable Care
    ("Peter Bridgman", "peter.bridgman@affordablecare.com", "Affordable Care", "affordablecare.com", "CEO", "ceo"),
    ("Nathan Kring", "nathan.kring@affordablecare.com", "Affordable Care", "affordablecare.com", "EVP & COO", "ceo"),
    ("Shinto Chakuncal", "shinto.chakuncal@affordablecare.com", "Affordable Care", "affordablecare.com", "VP, Operations", "vp_ops"),
    ("Deena Ali", "deena.ali@affordablecare.com", "Affordable Care", "affordablecare.com", "VP Field Operations Training & Development", "vp_ops"),
    ("Steven Woods", "steven.woods@affordablecare.com", "Affordable Care", "affordablecare.com", "VP of Field Operations", "vp_ops"),
    ("David Fenty", "david.fenty@affordablecare.com", "Affordable Care", "affordablecare.com", "Director of Field Operations", "vp_ops"),
    ("Bibi Grotberg", "bibi.grotberg@affordablecare.com", "Affordable Care", "affordablecare.com", "Director of Field Operations", "vp_ops"),
    ("Baltazar Torres", "baltazar.torres@affordablecare.com", "Affordable Care", "affordablecare.com", "Director of Field Operations", "regional"),
    ("Lisa Shannon", "lisa.shannon@affordablecare.com", "Affordable Care", "affordablecare.com", "Director of Field Operations", "regional"),
    ("Alok Jain Jr", "alok.jain@affordablecare.com", "Affordable Care", "affordablecare.com", "Sr. Director Patient Relationship Management", "cx"),
]

TEMPLATE_FNS = {
    "ceo": ceo_email,
    "vp_ops": vp_ops_email,
    "regional": regional_mgr_email,
    "cx": cx_email,
    "digital": digital_email,
    "growth": growth_email,
}


def main():
    os.makedirs("output", exist_ok=True)
    fieldnames = ["contact_name", "contact_email", "company_name", "domain",
                  "contact_title", "subject", "body"]

    rows_written = 0
    with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for name, email, company, domain, title, template_key in CONTACTS:
            first = name.split()[0]
            fn = TEMPLATE_FNS[template_key]
            email_data = fn(first, company)
            writer.writerow({
                "contact_name": name,
                "contact_email": email,
                "company_name": company,
                "domain": domain,
                "contact_title": title,
                "subject": email_data["subject"],
                "body": email_data["body"],
            })
            rows_written += 1

    print(f"Generated {rows_written} dental DSO outreach emails → {OUTPUT}")


if __name__ == "__main__":
    main()
