# Cold Email Automation System — Project Memory

## Working Directory
`/home/user/sales/`

## Branch
`claude/automate-cold-email-4LrfG`

## API
- Instantly.ai API v2, Bearer token auth
- Key stored in `.env` as `INSTANTLY_API_KEY`
- Variables use camelCase: `{{firstName}}`, `{{companyName}}`, `{{lastName}}`, `{{jobTitle}}`
- Email bodies must be HTML (`<div>` per line, `<div><br /></div>` for blank lines)
- Timezone: `America/Detroit`

## Live Campaigns
| Campaign | ID | Steps |
|---|---|---|
| Cost Angle | `672fa45d-ed45-463e-9198-6137ee7043d9` | 4 |
| Time Angle | `c5d69ff5-357b-42c6-bd3a-f5eff9c8ca22` | 3 |
| Social Proof | `0571c68e-e187-41c6-9e32-0cf7b8a7d84d` | 3 |

43 warm inboxes assigned to all 3 campaigns.

## Key Files
- `start.sh` / `stop.sh` — Start/stop entire system
- `run_forever.py` — Process manager (supervises reply_monitor + lead_watcher)
- `reply_monitor.py` — Polls Instantly every 2 min, auto-responds to replies with objection handling + Calendly
- `lead_watcher.py` — Watches `leads/incoming/` for CSVs, splits across 3 campaigns, uploads
- `replies/responder.py` — Classifies replies (8 categories), generates responses
- `instantly/client.py` — API client (v2, Bearer auth, retries)
- `instantly/campaigns.py` — Campaign CRUD
- `instantly/accounts.py` — Inbox management
- `instantly/leads.py` — Lead management
- `campaigns/ai_recruiting_sequences.yaml` — 3 recruiting sequences (clean copy, no spintax)
- `campaigns/automation.py` — End-to-end campaign creation from YAML
- `campaigns/niche_templates.yaml` — 7 industry templates
- `campaigns/batch_campaigns.yaml` — 15 niche/location combos
- `templates/library.yaml` — 5 reusable sequences
- `templates/engine.py` — Template engine with variable support
- `leads/scraper.py` — Apollo.io + Google Maps scraper
- `autopilot.py` — Full pipeline automation
- `automate_everything.py` — One-click setup
- `setup_outlook_inboxes.py` — Outlook inbox creation
- `inboxes/bulk_creator.py` — Bulk inbox orchestrator
- `inboxes/dns_setup.py` — SPF/DKIM/DMARC setup
- `webhooks/receiver.py` — Flask webhook server (port 8000)
- `webhooks/setup_webhooks.py` — Webhook registration CLI
- `main.py` — CLI entry point (7 command groups, 20+ commands)
- `config.yaml` — Global config (sending limits, schedule, deliverability)
- `SYSTEM_GUIDE.txt` — Full downloadable reference

## Calendly Link
https://calendly.com/realsideai

## Constructor Signatures (watch out)
- `BulkInboxCreator(strategy=, registry_path=, domain=, daily_limit=, warmup=)` — no `config=`
- `DNSSetup(domain)` — domain is required first arg

## Known API Quirks
- Follow-up emails use empty subject (`""`) to stay in same thread
- Schedule needs `schedules` array wrapper with specific timezone values
- `link_tracking=False`, `first_email_text_only=True`, `stop_on_reply=True` for best deliverability
