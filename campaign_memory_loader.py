#!/usr/bin/env python3
"""
Campaign Memory Loader — Provides persistent context for all campaign generators.

Loads campaign_memory.json and provides formatted prompt strings that can be
injected into Claude API calls to give every email generator consistent context
about Realside AI, winning/losing patterns, tone, objection handling, and more.

Usage:
    from campaign_memory_loader import get_memory_prompt, get_industry_context, get_objection_context

    # Full memory prompt (for system or user prompt injection)
    memory = get_memory_prompt()

    # Industry-specific context
    industry_ctx = get_industry_context("med_spa")

    # Objection-specific context
    objection_ctx = get_objection_context("how_much")
"""

import json
import os

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

_memory_cache = None
_memory_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "campaign_memory.json")


def _load_memory() -> dict:
    """Load campaign memory from JSON, caching the result."""
    global _memory_cache
    if _memory_cache is not None:
        return _memory_cache
    try:
        with open(_memory_path, encoding="utf-8") as f:
            _memory_cache = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Warning: Could not load campaign memory from {_memory_path}: {e}")
        _memory_cache = {}
    return _memory_cache


def reload_memory():
    """Force reload of campaign memory (useful if the file was updated)."""
    global _memory_cache
    _memory_cache = None
    return _load_memory()


# ---------------------------------------------------------------------------
# Main prompt builder
# ---------------------------------------------------------------------------


def get_memory_prompt(industry: str = None) -> str:
    """Return a formatted string for injection into Claude prompts.

    Includes company context, sender persona, winning/losing patterns,
    tone guidelines, case study summaries, social proof, and key rules.

    Args:
        industry: Optional industry key (e.g. "med_spa", "dental") to include
                  industry-specific context inline.

    Returns:
        A multi-line string ready to insert into a system or user prompt.
    """
    mem = _load_memory()
    if not mem:
        return ""

    company = mem.get("company", {})
    sender = mem.get("sender", {})
    winning = mem.get("winning_patterns", {})
    losing = mem.get("losing_patterns", {})
    tone = mem.get("tone_guidelines", {})
    case_studies = mem.get("case_studies", {})
    social_proof = mem.get("social_proof_snippets", [])

    # Build sections
    sections = []

    # Company context
    products = company.get("products", {})
    inbound = products.get("inbound_receptionist", {})
    outbound = products.get("outbound_agent", {})
    pricing = company.get("pricing", {})

    sections.append(f"""=== REALSIDE AI CONTEXT ===
Company: {company.get('name', 'Realside AI')} - {company.get('tagline', '')}
What we do: {company.get('what_we_do', '')}

Products:
1. {inbound.get('name', 'AI Inbound Receptionist')} ("{inbound.get('nickname', '')}") - {inbound.get('description', '')}
   Pain solved: {inbound.get('pain_solved', '')}
2. {outbound.get('name', 'AI Outbound Agent')} ("{outbound.get('nickname', '')}") - {outbound.get('description', '')}
   Pain solved: {outbound.get('pain_solved', '')}

Pricing: Starts at {pricing.get('starting_price', '$2,000/month')}. {pricing.get('framing', '')}
Anchor: {pricing.get('anchor_result', '')}
Calendar: {company.get('calendar_link', 'https://calendly.com/realsideai')}""")

    # Proven results
    results = company.get("proven_results", [])
    if results:
        results_str = "\n".join(f"- {r}" for r in results)
        sections.append(f"Proven Results:\n{results_str}")

    # Key differentiators
    diffs = company.get("differentiators", [])
    if diffs:
        diffs_str = "\n".join(f"- {d}" for d in diffs)
        sections.append(f"Differentiators:\n{diffs_str}")

    # Sender persona
    sections.append(f"""=== SENDER PERSONA ===
Name: {sender.get('name', 'Dylan Mitchell')}
Background: {sender.get('background', '')}
Sign off as: {sender.get('sign_off', 'Dylan')}
Email: {sender.get('email', '')}""")

    # Winning patterns
    email_patterns = winning.get("email_structure", [])
    ctas = winning.get("ctas_that_work", [])
    if email_patterns:
        patterns_str = "\n".join(f"- {p}" for p in email_patterns)
        sections.append(f"=== WINNING EMAIL PATTERNS ===\n{patterns_str}")
    if ctas:
        ctas_str = "\n".join(f"- {c}" for c in ctas)
        sections.append(f"CTAs that work:\n{ctas_str}")

    # Losing patterns (CRITICAL)
    never_do = losing.get("never_do", [])
    if never_do:
        never_str = "\n".join(f"- {n}" for n in never_do)
        sections.append(f"=== RULES (MUST FOLLOW) ===\n{never_str}")

    # Tone
    tone_rules = tone.get("rules", [])
    if tone_rules:
        tone_str = "\n".join(f"- {t}" for t in tone_rules)
        sections.append(f"Tone: {tone.get('overall', '')}\n{tone_str}")

    # Case study summaries
    if case_studies:
        cs_lines = []
        for key, cs in case_studies.items():
            cs_lines.append(f"- {cs.get('customer', key)}: {cs.get('result', '')}")
        sections.append(f"=== CASE STUDY SUMMARIES ===\n" + "\n".join(cs_lines))

    # Social proof snippets
    if social_proof:
        sp_str = "\n".join(f"- {s}" for s in social_proof)
        sections.append(f"=== SOCIAL PROOF (use sparingly, pick the most relevant) ===\n{sp_str}")

    # Industry-specific context (if requested)
    if industry:
        industry_section = get_industry_context(industry)
        if industry_section:
            sections.append(industry_section)

    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# Industry context
# ---------------------------------------------------------------------------


def get_industry_context(industry: str) -> str:
    """Return formatted industry-specific context for a given vertical.

    Args:
        industry: Industry key (e.g. "med_spa", "dental", "wellness", "staffing")
                  or a freeform string that will be matched against vertical names.

    Returns:
        Formatted string with pain points, talking points, and relevant stats.
        Empty string if no match found.
    """
    mem = _load_memory()
    industries = mem.get("industry_context", {})

    if not industry:
        return ""

    industry_lower = industry.lower().strip()

    # Direct key match
    if industry_lower in industries:
        return _format_industry(industry_lower, industries[industry_lower])

    # Try matching against vertical names
    for key, data in industries.items():
        verticals = [v.lower() for v in data.get("verticals", [])]
        if industry_lower in verticals or any(industry_lower in v for v in verticals):
            return _format_industry(key, data)

    # Fuzzy: check if the industry string contains any vertical keyword
    for key, data in industries.items():
        verticals = [v.lower() for v in data.get("verticals", [])]
        if any(v in industry_lower for v in verticals) or any(industry_lower in v for v in verticals):
            return _format_industry(key, data)

    return ""


def _format_industry(key: str, data: dict) -> str:
    """Format an industry context dict into a prompt-ready string."""
    pain_points = "\n".join(f"  - {p}" for p in data.get("pain_points", []))
    talking_points = "\n".join(f"  - {t}" for t in data.get("talking_points", []))
    stat = data.get("relevant_stat", "")

    return f"""=== INDUSTRY CONTEXT: {key.upper().replace('_', ' ')} ===
Pain points:
{pain_points}
Talking points:
{talking_points}
Key stat: {stat}"""


# ---------------------------------------------------------------------------
# Objection context
# ---------------------------------------------------------------------------


def get_objection_context(objection_type: str) -> str:
    """Return formatted objection handling context for a specific objection type.

    Args:
        objection_type: One of direct_intent, how_does_it_work, how_much,
                        send_proof, not_interested, tried_before, already_have, timing

    Returns:
        Formatted string with strategy and example response.
        Empty string if no match.
    """
    mem = _load_memory()
    objections = mem.get("objection_handling", {}).get("objections", {})

    if not objection_type:
        return ""

    obj = objections.get(objection_type.lower().strip())
    if not obj:
        return ""

    framework = mem.get("objection_handling", {}).get("framework", "")

    lines = [
        f"=== OBJECTION HANDLING: {objection_type.upper()} ===",
        f"Framework: {framework}",
        f"Description: {obj.get('description', '')}",
        f"Strategy: {obj.get('strategy', '')}",
    ]

    if obj.get("example_response"):
        lines.append(f"Example: {obj['example_response']}")
    if obj.get("example_response_first"):
        lines.append(f"First attempt: {obj['example_response_first']}")
    if obj.get("example_response_pushed"):
        lines.append(f"If pushed: {obj['example_response_pushed']}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Convenience: get all social proof snippets
# ---------------------------------------------------------------------------


def get_social_proof() -> list:
    """Return list of social proof snippet strings."""
    mem = _load_memory()
    return mem.get("social_proof_snippets", [])


def get_case_studies() -> dict:
    """Return case studies dict keyed by slug."""
    mem = _load_memory()
    return mem.get("case_studies", {})


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    import sys

    industry_arg = sys.argv[1] if len(sys.argv) > 1 else None
    print(get_memory_prompt(industry=industry_arg))
    print("\n" + "=" * 60)
    print(f"Memory loaded from: {_memory_path}")
    print(f"Character count: {len(get_memory_prompt(industry=industry_arg))}")
