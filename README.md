# Cold Email System

Send personalized cold outreach emails via Gmail SMTP.

## Setup

1. **Enable Gmail App Password** (required since Gmail blocks less-secure apps):
   - Go to https://myaccount.google.com/security
   - Enable 2-Step Verification if not already enabled
   - Go to https://myaccount.google.com/apppasswords
   - Create an App Password (select "Mail" and your device)
   - Copy the 16-character password

2. **Configure credentials**:
   - Edit `config.json` and replace `YOUR_APP_PASSWORD_HERE` with your Gmail App Password

3. **Add your contacts** to `contacts.csv` with columns: `first_name,last_name,email,company,role`

## Usage

Preview emails without sending (dry run):
```bash
python send_emails.py --dry-run
```

Send cold outreach emails:
```bash
python send_emails.py --template templates/cold_outreach.txt --contacts contacts.csv
```

Send follow-up emails:
```bash
python send_emails.py --template templates/follow_up.txt --contacts contacts.csv
```

### Options
- `--template` - Path to email template (default: `templates/cold_outreach.txt`)
- `--contacts` - Path to contacts CSV (default: `contacts.csv`)
- `--dry-run` - Preview emails without sending
- `--delay` - Seconds between emails (default: 5)

## Templates

Templates use `${variable}` placeholders that map to CSV columns:
- `${first_name}`, `${last_name}`, `${email}`, `${company}`, `${role}`

Create custom templates in the `templates/` directory.
