# Realside AI - Marketing Agency Outreach System

A complete marketing engine to drive 30-100+ meetings/month for Realside AI at the lowest possible cost per meeting.

## What Realside AI Sells
1. **CRM Reactivation Agent** — AI that mines your dead CRM leads and books them as appointments
2. **Inbound Voice Agent** — AI phone agent that answers every call 24/7 and books appointments

## System Overview

```
┌─────────────────────────────────────────────────────┐
│              LEAD SOURCING (Apollo)                  │
│   Home Services · Real Estate · Insurance · Dental  │
│              800 new leads/week                      │
└──────────────────┬──────────────────────────────────┘
                   │
          ┌────────┴────────┐
          ▼                 ▼
┌──────────────────┐ ┌──────────────────┐
│   COLD EMAIL     │ │  LOOM VIDEO      │
│   (Instantly)    │ │  OUTREACH        │
│   200/day        │ │  20-30/day       │
│   CPM: $2-5      │ │  CPM: $1-3       │
└────────┬─────────┘ └────────┬─────────┘
         │                    │
         ▼                    ▼
┌──────────────────────────────────────────┐
│            LINKEDIN ORGANIC              │
│   Posts · Comments · DMs · Connections   │
│   30 min/day · CPM: $0                   │
└──────────────────┬───────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────┐
│         MEETING BOOKING (Calendly)       │
│   Pre-meeting nurture · SMS reminders    │
│   Target: 100 meetings/month             │
└──────────────────┬───────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────┐
│         TRACKING & OPTIMIZATION          │
│   Cost per meeting · Reply rates · ROI   │
│   Weekly reports · A/B testing           │
└──────────────────────────────────────────┘
```

## Quick Start

### 1. Generate Sample Contacts
```bash
python scripts/apollo_lead_search.py --sample
```

### 2. Generate Email Campaigns for Instantly
```bash
# CRM Reactivation sequence
python scripts/generate_sequences.py output/sample_contacts.csv \
  --sender-name "Dylan" \
  --sender-email "dylan@realsideai.com" \
  --sequence crm_reactivation

# Voice Agent sequence
python scripts/generate_sequences.py output/sample_contacts.csv \
  --sender-name "Dylan" \
  --sender-email "dylan@realsideai.com" \
  --sequence voice_agent

# Combo (both products)
python scripts/generate_sequences.py output/sample_contacts.csv \
  --sender-name "Dylan" \
  --sender-email "dylan@realsideai.com" \
  --sequence combo
```

### 3. View Apollo Search Instructions
```bash
python scripts/apollo_lead_search.py
```

### 4. Initialize Campaign Tracker
```bash
python scripts/campaign_tracker.py init
python scripts/campaign_tracker.py targets
python scripts/campaign_tracker.py log-activity
python scripts/campaign_tracker.py report
```

### 5. View Weekly Ops Checklist
```bash
python scripts/weekly_ops_checklist.py
```

## Directory Structure

```
sales/
├── config/
│   ├── icp_config.json              # ICP definitions, verticals, pain points
│   └── campaign_config.json         # Channel configs, budgets, cost analysis
├── scripts/
│   ├── generate_sequences.py        # Email sequence generator → Instantly CSV
│   ├── apollo_lead_search.py        # Apollo search helper + sample data
│   ├── campaign_tracker.py          # Track metrics, log meetings, generate reports
│   └── weekly_ops_checklist.py      # Weekly operational checklist
├── templates/
│   ├── email_sequences/
│   │   ├── crm_reactivation_sequence.json  # 4-step CRM reactivation emails
│   │   ├── voice_agent_sequence.json       # 4-step voice agent emails
│   │   └── combo_sequence.json             # 3-step combined pitch
│   ├── linkedin/
│   │   └── organic_playbook.json    # Posts, DM scripts, connection templates, ad campaigns
│   └── loom_scripts/
│       └── video_outreach_scripts.json  # Video scripts + daily workflow
├── booking/
│   └── pre_meeting_nurture.json     # Calendly setup, nurture emails, no-show reduction
├── tracking/                        # Auto-generated tracking CSVs
└── output/                          # Generated campaigns and reports
```

## Monthly Budget (Without LinkedIn Ads)

| Tool | Cost | Purpose |
|------|------|---------|
| Instantly | $97/mo | Email sending + warmup |
| Apollo | $49/mo | Lead sourcing |
| Domains (5) | $5/mo | Cold email sending domains |
| Google Workspace (6) | $36/mo | Email accounts |
| Loom Pro | $15/mo | Video outreach |
| **Total** | **$202/mo** | **~$2/meeting at 100 meetings/mo** |

## Channel Priority (Cheapest First)

1. **Cold Email** — $2-5/meeting, highest volume
2. **LinkedIn Organic** — $0/meeting, builds brand
3. **Loom Video** — $1-3/meeting, highest reply rates
4. **Weekly Webinar** — $0-5/meeting, builds authority
5. **Facebook Groups** — $0/meeting, targeted
6. **Referral Program** — Variable, highest close rate
7. **LinkedIn Ads** — $50-150/meeting (last resort)
