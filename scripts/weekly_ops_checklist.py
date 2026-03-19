#!/usr/bin/env python3
"""
Realside AI - Weekly Marketing Ops Checklist
Prints the weekly operational checklist for running the marketing agency system.
Run every Monday to stay on track.
"""

from datetime import datetime


def print_checklist():
    week_start = datetime.now().strftime("%B %d, %Y")

    print(f"""
{'='*70}
REALSIDE AI - WEEKLY MARKETING OPS CHECKLIST
Week of: {week_start}
{'='*70}

MONDAY — Lead Sourcing Day
{'─'*50}
[ ] Pull 200 leads from Apollo (Home Services vertical)
    → Filter: Owner/GM, 5-100 employees, US, has email
    → Export as CSV
[ ] Clean list: remove duplicates, verify emails
[ ] Import Step 1 CSV into Instantly campaign
[ ] Post LinkedIn content (Dead Lead Revival story)
[ ] Send 25 LinkedIn connection requests to Home Services ICPs
[ ] 15 min commenting on ICP posts

TUESDAY — Outreach Day
{'─'*50}
[ ] Pull 200 leads from Apollo (Real Estate vertical)
[ ] Record 20 Loom videos for yesterday's Home Services leads
[ ] Send Loom videos via email + LinkedIn DM
[ ] Check Instantly dashboard — reply to all positive responses
[ ] Post LinkedIn content (Missed Call story)
[ ] Send 25 LinkedIn connection requests to Real Estate ICPs
[ ] 15 min commenting on ICP posts
[ ] DM any new LinkedIn connections

WEDNESDAY — Follow-Up Day
{'─'*50}
[ ] Pull 100 leads from Apollo (Insurance vertical)
[ ] Record 20 Loom videos for Real Estate leads
[ ] Review all Instantly replies — respond within 2 hours
[ ] Follow up with any Loom viewers (>75% watched)
[ ] Post LinkedIn content (Building in Public)
[ ] Send 25 LinkedIn connection requests to Insurance ICPs
[ ] Book meetings from warm replies → Calendly
[ ] Log all meetings in campaign_tracker.py

THURSDAY — Conversion Day
{'─'*50}
[ ] Pull 100 leads from Apollo (Dental/Medical or Auto vertical)
[ ] Record 15 Loom videos for Insurance leads
[ ] Focus: Follow up on ALL pending conversations
[ ] Send meeting confirmations + pre-meeting nurture emails
[ ] Post LinkedIn content (CRM Reactivation story)
[ ] Send 25 LinkedIn connection requests
[ ] Prep for any meetings scheduled this week

FRIDAY — Review & Optimize Day
{'─'*50}
[ ] Run: python scripts/campaign_tracker.py report
[ ] Review metrics: reply rate, meetings booked, CPM
[ ] A/B test: Change subject lines on worst-performing sequence
[ ] Clean up Instantly bounces and unsubscribes
[ ] Prep next week's LinkedIn content (batch write 5 posts)
[ ] Record 1 webinar/demo for next week's promotion
[ ] Update tracking spreadsheet with all meetings & outcomes
[ ] Plan next week's vertical focus based on what's converting

{'='*70}
DAILY NON-NEGOTIABLES (Every Day, 30 min)
{'='*70}
[ ] Check Instantly for replies — respond within 2 hours
[ ] Post 1 LinkedIn post (pre-written)
[ ] Send 20-25 LinkedIn connection requests
[ ] 15 min commenting on ICP posts
[ ] DM new connections with opener
[ ] Log activity in campaign_tracker.py

{'='*70}
MONTHLY TARGETS
{'='*70}
  Cold Email:        50 meetings/mo  |  Budget: $242/mo   |  CPM: $4.84
  LinkedIn Organic:  15 meetings/mo  |  Budget: $0/mo     |  CPM: $0
  Loom Video:        15 meetings/mo  |  Budget: $15/mo    |  CPM: $1.00
  Webinar:           10 meetings/mo  |  Budget: $0/mo     |  CPM: $0
  FB Groups:          5 meetings/mo  |  Budget: $0/mo     |  CPM: $0
  LinkedIn Ads:       5 meetings/mo  |  Budget: $500/mo   |  CPM: $100
  ─────────────────────────────────────────────────────────────────
  TOTAL:            100 meetings/mo  |  Budget: $757/mo   |  CPM: $7.57

{'='*70}
COST BREAKDOWN (Monthly)
{'='*70}
  Instantly:         $97/mo
  Apollo:            $49/mo
  Domains (5):       $5/mo ($60/yr)
  Google Workspace:  $36/mo (6 accounts)
  Loom Pro:          $15/mo
  LinkedIn Ads:      $500/mo (optional — cut if CPM too high)
  ─────────────────
  WITHOUT Ads:       $202/mo → ~$2.12/meeting
  WITH Ads:          $702/mo → ~$7.02/meeting

  NOTE: At 100 meetings/month with 20% close rate and $1,000/mo avg deal,
        that's 20 new clients × $1,000 = $20,000 MRR from $702 spend.
        That's a 28x ROI.
""")


if __name__ == "__main__":
    print_checklist()
