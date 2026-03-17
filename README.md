# Cold Email Automation System

Fully automated cold email system powered by [Instantly.ai](https://instantly.ai). Generate free inboxes, set up deliverability, create campaigns from templates, and send at scale.

## Features

- **Instantly API Integration** — Full API client for campaigns, leads, accounts, and analytics
- **Free Inbox Provisioning** — Generate and manage Outlook/Hotmail and Zoho Mail inboxes at no cost
- **DNS & Deliverability** — Auto-generate SPF, DKIM, DMARC records; verify setup; Cloudflare auto-config
- **Template Library** — 5 ready-to-use email sequences with spintax for unique variants
- **Campaign Automation** — Create, launch, monitor, and scale campaigns from the CLI
- **Lead Management** — CSV import with auto-deduplication and field normalization
- **Health Monitoring** — Auto-pause campaigns on high bounce rates, performance reports

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set up your API key
cp .env.example .env
# Edit .env and add your Instantly API key

# 3. Test connection
python main.py setup

# 4. Generate free inboxes
python main.py inboxes checklist --strategy outlook_free --count 5

# 5. Add inboxes after creating them
python main.py inboxes bulk-add --file inboxes/inbox_plan.csv

# 6. Create and launch a campaign
python main.py campaign create --template "SaaS Cold Outreach" --leads leads/sample_leads.csv
```

## Getting Free Inboxes

### Method 1: Outlook/Hotmail (Fastest)

Free personal email accounts with SMTP/IMAP access.

```bash
# Generate email name suggestions
python main.py inboxes generate --strategy outlook_free --count 10

# Get step-by-step creation guide
python main.py inboxes checklist --strategy outlook_free --count 5
```

1. Go to [signup.live.com](https://signup.live.com)
2. Create accounts using the suggested names
3. Enable IMAP: Settings → Mail → Sync email → POP and IMAP
4. Fill in passwords in `inboxes/inbox_plan.csv`
5. Run: `python main.py inboxes bulk-add --file inboxes/inbox_plan.csv`

**Limits:** ~30 emails/day per inbox. Use 5-10 inboxes for 150-300 emails/day.

### Method 2: Zoho Mail (Best for Custom Domains)

Free email hosting for 1 domain, up to 5 users.

```bash
# Generate setup guide for your domain
python main.py inboxes checklist --strategy zoho_free --domain yourdomain.com --count 5
```

1. Buy a cheap domain ($2-3 from Namecheap/Cloudflare)
2. Sign up at [zoho.com/mail](https://www.zoho.com/mail/) (Forever Free Plan)
3. Add your domain and verify ownership
4. Set up DNS records: `python main.py dns generate --domain yourdomain.com`
5. Create up to 5 email accounts
6. Enable IMAP and connect to Instantly

**Pro tip:** Buy 3-5 domains at $2-3 each = 15-25 free inboxes for under $15.

## DNS Setup for Deliverability

Proper DNS records are critical for inbox placement.

```bash
# Generate all required DNS records
python main.py dns generate --domain yourdomain.com --provider zoho

# Verify records are set correctly
python main.py dns verify --domain yourdomain.com

# Auto-add via Cloudflare (if configured)
python main.py dns cloudflare-setup --domain yourdomain.com

# Full checklist
python main.py dns checklist --domain yourdomain.com
```

### Required Records
| Record | Purpose |
|--------|---------|
| MX | Routes email to your provider |
| SPF | Authorizes sending servers |
| DKIM | Signs emails cryptographically |
| DMARC | Authentication policy |
| CNAME (track) | Custom tracking domain for Instantly |

## Creating Campaigns

### Browse Templates

```bash
python main.py templates list
python main.py templates preview --name "SaaS Cold Outreach"
```

Available templates:
- **SaaS Cold Outreach** — General B2B SaaS product outreach
- **Agency Services** — Agency pitching services to clients
- **Partnership** — Partnership and collaboration outreach
- **Recruiting** — Talent recruiting outreach
- **Consulting** — Consulting services pitch

### Create a Campaign

```bash
# From template + leads CSV
python main.py campaign create \
  --template "SaaS Cold Outreach" \
  --leads leads/sample_leads.csv \
  --name "My First Campaign"

# Launch it
python main.py campaign launch --id <campaign_id>

# Monitor
python main.py campaign stats --id <campaign_id>
python main.py campaign health --id <campaign_id>
python main.py campaign report
```

### Scale Up

```bash
# Add more leads to running campaign
python main.py campaign add-leads --id <campaign_id> --file more_leads.csv
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `setup` | Interactive setup wizard |
| `dashboard` | Overview dashboard |
| **Inboxes** | |
| `inboxes generate` | Generate inbox name suggestions |
| `inboxes add` | Add single inbox to Instantly |
| `inboxes bulk-add` | Add inboxes from CSV |
| `inboxes list` | List connected inboxes |
| `inboxes warmup-all` | Enable warmup on all |
| `inboxes status` | Warmup status |
| `inboxes checklist` | Step-by-step inbox creation guide |
| **Campaigns** | |
| `campaign create` | Create from template + leads |
| `campaign list` | List all campaigns |
| `campaign launch` | Launch a campaign |
| `campaign pause` | Pause a campaign |
| `campaign stats` | Campaign analytics |
| `campaign add-leads` | Add leads to campaign |
| `campaign health` | Check health, auto-pause |
| `campaign report` | Performance report |
| **Leads** | |
| `leads import` | Import from CSV |
| `leads sample` | Generate sample CSV |
| **Templates** | |
| `templates list` | List available templates |
| `templates preview` | Preview with sample data |
| **DNS** | |
| `dns generate` | Generate DNS records |
| `dns verify` | Verify DNS setup |
| `dns checklist` | DNS setup checklist |
| `dns cloudflare-setup` | Auto-add via Cloudflare |

## Best Practices

1. **Warm up inboxes** for 14+ days before sending campaigns
2. **Keep volume under 50/day** per inbox for best deliverability
3. **Use spintax** — every email should be unique to avoid spam filters
4. **Don't track clicks** — link tracking hurts deliverability
5. **Monitor bounce rates** — pause campaigns if bounces exceed 5%
6. **Rotate domains** — don't send everything from one domain
7. **Send during business hours** — 8am-5pm recipient timezone
8. **Clean your lists** — remove invalid emails before importing

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `INSTANTLY_API_KEY` | Yes | Instantly.ai API key |
| `CLOUDFLARE_API_TOKEN` | No | For auto DNS setup |
| `CLOUDFLARE_ACCOUNT_ID` | No | Cloudflare account |
| `NAMECHEAP_API_USER` | No | Domain purchasing |
| `NAMECHEAP_API_KEY` | No | Domain purchasing |

## Project Structure

```
sales/
├── main.py                    # CLI entry point
├── config.yaml                # System configuration
├── requirements.txt           # Python dependencies
├── .env                       # API keys (not committed)
├── instantly/                 # Instantly API integration
│   ├── client.py              # Low-level API client
│   ├── campaigns.py           # Campaign management
│   ├── accounts.py            # Email account management
│   └── leads.py               # Lead management
├── inboxes/                   # Free inbox provisioning
│   ├── outlook_creator.py     # Outlook/Hotmail inbox helper
│   ├── zoho_creator.py        # Zoho Mail inbox helper
│   ├── bulk_creator.py        # Bulk inbox orchestrator
│   └── dns_setup.py           # DNS record management
├── campaigns/                 # Campaign automation
│   └── automation.py          # End-to-end campaign engine
├── templates/                 # Email templates
│   ├── engine.py              # Template rendering engine
│   └── library.yaml           # Ready-to-use sequences
├── leads/                     # Lead data
│   └── sample_leads.csv       # Example leads file
└── utils/                     # Utilities
    └── spintax.py             # Spintax parser
```
