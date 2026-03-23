#!/usr/bin/env python3
"""
Objection Handler for Prospect Replies

Takes a CSV of prospect replies (with objection type classification) and uses
Claude to generate appropriate responses based on the Imperium framework and
Realside AI context. Loads case studies for social proof and config for sender
info, calendar link, and product details.

Usage:
    python objection_handler.py --input replies.csv --output objection_responses.csv
    python objection_handler.py --input replies.csv --config config.json

Input CSV columns:
    company_name, domain, contact_name, contact_email, contact_title,
    original_message, objection, reply_type

    reply_type values:
        direct_intent, how_does_it_work, how_much, send_proof,
        not_interested, tried_before, already_have, timing, other

Output CSV columns:
    company_name, domain, contact_name, contact_email, subject, body,
    action, reply_type, sender_email, sender_name
"""

import argparse
import csv
import json
import os
import re
import sys

try:
    import anthropic
except ImportError:
    print("Error: anthropic package required. Install with: pip install anthropic")
    sys.exit(1)

try:
    from campaign_memory_loader import get_memory_prompt, get_objection_context
except ImportError:
    def get_memory_prompt(**kwargs):
        return ""
    def get_objection_context(objection_type):
        return ""


VALID_REPLY_TYPES = {
    "direct_intent",
    "how_does_it_work",
    "how_much",
    "send_proof",
    "not_interested",
    "tried_before",
    "already_have",
    "timing",
    "other",
}

VALID_ACTIONS = {
    "send_calendly",
    "send_loom",
    "send_case_study",
    "nurture",
    "do_not_reply",
}

DEFAULT_CONFIG_PATH = "config.json"


def load_config(config_path: str) -> dict:
    """Load configuration from JSON file."""
    try:
        with open(config_path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: Config file not found: {config_path}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in config file: {e}")
        sys.exit(1)


def load_case_studies(case_studies_path: str) -> str:
    """Load all case studies from the given directory into a single string."""
    if not os.path.isdir(case_studies_path):
        print(f"Warning: Case studies directory not found: {case_studies_path}")
        return ""

    studies = []
    for filename in sorted(os.listdir(case_studies_path)):
        filepath = os.path.join(case_studies_path, filename)
        if os.path.isfile(filepath):
            try:
                with open(filepath, encoding="utf-8") as f:
                    content = f.read().strip()
                if content:
                    studies.append(f"--- {filename} ---\n{content}")
            except Exception as e:
                print(f"Warning: Could not read {filepath}: {e}")
    return "\n\n".join(studies)


def read_input_csv(filepath: str) -> list[dict]:
    """Read prospect replies from CSV."""
    required_columns = {
        "company_name", "domain", "contact_name", "contact_email",
        "contact_title", "original_message", "objection", "reply_type",
    }
    rows = []
    with open(filepath, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            print("Error: CSV file is empty or has no header row")
            sys.exit(1)
        missing = required_columns - set(reader.fieldnames)
        if missing:
            print(f"Error: CSV is missing required columns: {', '.join(sorted(missing))}")
            sys.exit(1)
        for row in reader:
            reply_type = row.get("reply_type", "").strip().lower()
            if reply_type not in VALID_REPLY_TYPES:
                print(f"Warning: Unknown reply_type '{reply_type}' for {row.get('contact_name', 'unknown')}, defaulting to 'other'")
                row["reply_type"] = "other"
            else:
                row["reply_type"] = reply_type
            rows.append(row)
    return rows


def write_output_csv(filepath: str, results: list[dict]):
    """Write objection responses to CSV."""
    if not results:
        print("No results to write.")
        return

    fieldnames = [
        "company_name", "domain", "contact_name", "contact_email",
        "subject", "body", "action", "reply_type",
        "sender_email", "sender_name",
    ]
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)
    print(f"\nWrote {len(results)} objection responses to {filepath}")


def generate_objection_response(
    client: anthropic.Anthropic,
    company_name: str,
    domain: str,
    contact_name: str,
    contact_email: str,
    contact_title: str,
    original_message: str,
    objection: str,
    reply_type: str,
    product_description: str,
    case_studies: str,
    calendar_link: str,
    sender_name: str,
    sender_email: str,
) -> dict:
    """Use Claude to generate an objection response based on the Imperium framework."""

    # Inject campaign memory and objection-specific context
    memory_context = get_memory_prompt()
    objection_context = get_objection_context(reply_type)

    prompt = f"""You are an expert SDR trained in selling to service businesses (med spas, dental offices, wellness centers, aesthetic clinics, IV clinics).

{memory_context}

{objection_context}

OFFER:
Realside AI builds AI Employees for service businesses.
{product_description}

CASE STUDIES (use for social proof where relevant):
{case_studies}

PROSPECT INFO:
- Company: {company_name}
- Domain: {domain}
- Contact: {contact_name}
- Email: {contact_email}
- Title: {contact_title}

ORIGINAL MESSAGE SENT TO PROSPECT:
{original_message}

PROSPECT'S REPLY:
{objection}

REPLY TYPE: {reply_type}

REPLY TYPE CONTEXT:
- "direct_intent": They want to learn more or are interested. Book the call.
- "how_does_it_work": They want to understand the product. Explain briefly, then steer to a demo call.
- "how_much": Asking about pricing. Give a range, emphasize ROI, steer to a call.
- "send_proof": They want evidence it works. Share a case study, then steer to a call.
- "not_interested": They said no. Empathize, reframe with a quick insight, leave door open.
- "tried_before": They tried AI or similar before and it didn't work. Differentiate Realside, offer proof.
- "already_have": They have a solution in place. Acknowledge, plant a seed about what they might be missing.
- "timing": Bad timing. Respect it, offer a future touchpoint.
- "other": Anything else. Read the reply carefully and respond appropriately.

IMPERIUM FRAMEWORK RULES:
1. Tone: friendly, confident, value-driven
2. Short, punchy sentences
3. Speak to pain points and desired outcomes
4. Spark curiosity and open the door to a short call
5. Avoid sounding robotic or overly formal
6. Never use '--' in messaging
7. For objections: empathize first, reframe with logic or social proof, end with a low-friction CTA
8. Keep the response under 120 words
9. CTA: Ask what days work for a call (no calendly links)
10. Sign off with sender's first name only

YOUR TASK:
Write a reply email to the prospect's objection. Follow the Imperium framework rules above.

Return your response as a JSON object with these exact keys:
- "subject": email subject line (short, relevant, no "Re:" prefix)
- "body": full email body (plain text, use \\n for newlines)
- "action": one of "send_calendly", "send_loom", "send_case_study", "nurture", "do_not_reply"
  - "send_calendly": response steers toward booking a call
  - "send_loom": response includes or promises a video walkthrough
  - "send_case_study": response shares or references a case study
  - "nurture": soft touch, keep warm for later
  - "do_not_reply": prospect clearly does not want contact (e.g., hostile unsubscribe)

Return ONLY the JSON object, no markdown formatting."""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text.strip()

    # Extract JSON from response (handle markdown code blocks)
    json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if json_match:
        text = json_match.group(1)
    else:
        # Try to find raw JSON object
        json_match = re.search(r"\{.*\}", text, re.DOTALL)
        if json_match:
            text = json_match.group(0)

    try:
        result = json.loads(text)
        if not isinstance(result, dict):
            raise ValueError("Expected a JSON object")
        # Validate action field
        action = result.get("action", "nurture")
        if action not in VALID_ACTIONS:
            result["action"] = "nurture"
    except (json.JSONDecodeError, ValueError):
        # Fallback response
        result = {
            "subject": f"Quick note for {contact_name}",
            "body": f"Hi {contact_name},\n\nThanks for getting back to me. We're helping businesses like {company_name} capture more revenue with AI.\n\nWhat days work for a call?\n\nBest,\n{sender_name.split()[0]}",
            "action": "send_calendly",
        }

    return result


def main():
    parser = argparse.ArgumentParser(description="Objection Handler for Prospect Replies")
    parser.add_argument("--input", required=True, help="Input CSV with prospect replies")
    parser.add_argument("--output", default="objection_responses.csv", help="Output CSV path (default: objection_responses.csv)")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, help=f"Config JSON path (default: {DEFAULT_CONFIG_PATH})")
    args = parser.parse_args()

    # Load config
    config = load_config(args.config)

    sender_email = config.get("sender_email", "dylan.realside@gmail.com")
    sender_name = config.get("sender_name", "Dylan Mitchell")
    product_description = config.get("product_description", "")
    calendar_link = config.get("calendar_link", "https://calendly.com/realsideai")
    case_studies_path = config.get("case_studies_path", "case_studies")

    # Resolve case_studies_path relative to config file directory
    config_dir = os.path.dirname(os.path.abspath(args.config))
    if not os.path.isabs(case_studies_path):
        case_studies_path = os.path.join(config_dir, case_studies_path)

    # Get API key: config first, then env var
    api_key = config.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: No Anthropic API key found in config.json or ANTHROPIC_API_KEY environment variable")
        print("Set it in config.json as 'anthropic_api_key' or with: export ANTHROPIC_API_KEY=your-key-here")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    # Load case studies
    case_studies = load_case_studies(case_studies_path)
    if case_studies:
        print(f"Loaded case studies from {case_studies_path}")
    else:
        print("Warning: No case studies loaded. Responses will lack social proof examples.")

    # Read prospect replies
    prospects = read_input_csv(args.input)
    print(f"Loaded {len(prospects)} prospect replies from {args.input}")

    results = []
    for i, prospect in enumerate(prospects, 1):
        company_name = prospect["company_name"].strip()
        domain = prospect["domain"].strip()
        contact_name = prospect["contact_name"].strip()
        contact_email = prospect["contact_email"].strip()
        contact_title = prospect["contact_title"].strip()
        original_message = prospect["original_message"].strip()
        objection = prospect["objection"].strip()
        reply_type = prospect["reply_type"].strip()

        print(f"\n[{i}/{len(prospects)}] Handling {reply_type} objection from {contact_name} at {company_name}...")

        response = generate_objection_response(
            client=client,
            company_name=company_name,
            domain=domain,
            contact_name=contact_name,
            contact_email=contact_email,
            contact_title=contact_title,
            original_message=original_message,
            objection=objection,
            reply_type=reply_type,
            product_description=product_description,
            case_studies=case_studies,
            calendar_link=calendar_link,
            sender_name=sender_name,
            sender_email=sender_email,
        )

        results.append({
            "company_name": company_name,
            "domain": domain,
            "contact_name": contact_name,
            "contact_email": contact_email,
            "subject": response.get("subject", ""),
            "body": response.get("body", ""),
            "action": response.get("action", "nurture"),
            "reply_type": reply_type,
            "sender_email": sender_email,
            "sender_name": sender_name,
        })

        print(f"  Action: {response.get('action', 'N/A')} | Subject: {response.get('subject', 'N/A')}")

    # Write output
    write_output_csv(args.output, results)
    print("\nDone! Review the objection responses before sending.")


if __name__ == "__main__":
    main()
