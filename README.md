# Sales Email Outreach

Generate personalized sales outreach emails from templates and a contacts CSV.

## Quick Start

```bash
python generate_emails.py
```

This reads `templates/cold_outreach.txt` and `contacts.csv`, then writes personalized emails to `output/`.

## Usage

```bash
python generate_emails.py --template templates/follow_up.txt --contacts contacts.csv --output output
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--template` | `templates/cold_outreach.txt` | Path to the email template file |
| `--contacts` | `contacts.csv` | Path to the contacts CSV |
| `--output` | `output` | Output directory for generated emails |

## Customizing Templates

Templates live in `templates/` and use `${placeholder}` syntax. Available placeholders match the CSV column headers:

- `${first_name}`, `${last_name}`, `${email}`, `${company}`, `${role}`

To add a new template, create a `.txt` file in `templates/` using these placeholders.

## Contacts CSV Format

```csv
first_name,last_name,email,company,role
Alice,Johnson,alice@acmecorp.com,Acme Corp,VP of Sales
```
