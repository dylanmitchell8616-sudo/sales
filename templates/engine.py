"""Template engine for cold email campaigns.

Loads email templates from YAML files, resolves spintax and variable
placeholders, and provides helpers for personalization and A/B testing.
"""

import re
import random
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

from utils.spintax import resolve_spintax, generate_variants


# Pattern for {{variable}} placeholders (double curly braces)
_VAR_PATTERN = re.compile(r"\{\{(\w+)\}\}")


class TemplateEngine:
    """Engine for loading, validating, rendering, and testing email templates.

    Usage::

        engine = TemplateEngine()
        engine.load_library("templates/library.yaml")

        lead = {"first_name": "Jane", "company": "Acme", "title": "VP Sales"}
        rendered = engine.render("saas_cold_outreach", step=0, lead=lead)
        print(rendered["subject"], rendered["body"])
    """

    def __init__(self, library_path: Optional[str] = None):
        """Initialize the template engine.

        Args:
            library_path: Optional path to a YAML template library file.
                          If provided, templates are loaded immediately.
        """
        self.sequences: dict[str, dict] = {}
        if library_path:
            self.load_library(library_path)

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load_library(self, path: str) -> None:
        """Load email sequences from a YAML library file.

        Args:
            path: Path to the YAML file containing sequence definitions.

        Raises:
            FileNotFoundError: If the YAML file does not exist.
            ValueError: If the YAML structure is invalid.
        """
        file_path = Path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"Template library not found: {path}")

        with open(file_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not isinstance(data, dict) or "sequences" not in data:
            raise ValueError(
                "Template library must be a YAML dict with a top-level 'sequences' key."
            )

        for seq in data["sequences"]:
            name = seq.get("name")
            if not name:
                raise ValueError("Each sequence must have a 'name' field.")
            self.sequences[name] = seq

        print(f"  Loaded {len(self.sequences)} sequence(s) from {path}")

    def add_sequence(self, sequence: dict) -> None:
        """Programmatically add a sequence definition.

        Args:
            sequence: Dict with keys: name, description, steps.
        """
        name = sequence.get("name")
        if not name:
            raise ValueError("Sequence must have a 'name' field.")
        self.sequences[name] = sequence

    def list_sequences(self) -> list[str]:
        """Return the names of all loaded sequences."""
        return list(self.sequences.keys())

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render(self, sequence_name: str, step: int, lead: dict,
               seed: Optional[int] = None) -> dict:
        """Render a specific step of a sequence for a given lead.

        Resolves spintax first, then substitutes {{variable}} placeholders
        using lead data and built-in personalization helpers.

        Args:
            sequence_name: Name of the sequence to use.
            step: Zero-based step index within the sequence.
            lead: Dict of lead data (e.g. first_name, company, title).
            seed: Optional RNG seed for reproducible spintax resolution.

        Returns:
            Dict with keys 'subject' and 'body' containing fully rendered text.

        Raises:
            KeyError: If the sequence name is not loaded.
            IndexError: If the step index is out of range.
        """
        if sequence_name not in self.sequences:
            raise KeyError(f"Sequence not found: {sequence_name}")

        seq = self.sequences[sequence_name]
        steps = seq.get("steps", [])

        if step < 0 or step >= len(steps):
            raise IndexError(
                f"Step {step} out of range for sequence '{sequence_name}' "
                f"(has {len(steps)} steps)."
            )

        template_step = steps[step]
        rng = random.Random(seed)

        # Build the full variable context (lead data + helpers)
        context = self._build_context(lead)

        subject = self._render_string(template_step["subject"], context, rng)
        body = self._render_string(template_step["body"], context, rng)

        return {
            "subject": subject,
            "body": body,
            "delay_days": template_step.get("delay_days", 0),
        }

    def render_all_steps(self, sequence_name: str, lead: dict,
                         seed: Optional[int] = None) -> list[dict]:
        """Render every step of a sequence for a lead.

        Args:
            sequence_name: Name of the sequence.
            lead: Lead data dict.
            seed: Optional RNG seed.

        Returns:
            List of rendered step dicts (subject, body, delay_days).
        """
        seq = self.sequences[sequence_name]
        steps = seq.get("steps", [])
        return [self.render(sequence_name, i, lead, seed=seed) for i in range(len(steps))]

    def _render_string(self, text: str, context: dict,
                       rng: random.Random) -> str:
        """Resolve spintax then substitute variables in a string."""
        # Step 1: resolve spintax {A|B|C}
        resolved = resolve_spintax(text, rng)

        # Step 2: substitute {{variable}} placeholders
        def _replace(match):
            key = match.group(1)
            return str(context.get(key, match.group(0)))

        return _VAR_PATTERN.sub(_replace, resolved)

    # ------------------------------------------------------------------
    # Personalization helpers
    # ------------------------------------------------------------------

    def _build_context(self, lead: dict) -> dict:
        """Build a variable context dict from lead data plus built-in helpers.

        Built-in variables added automatically:
            - greeting: time-of-day greeting (Good morning / afternoon / evening)
            - company_compliment: a randomized compliment about the lead's company
            - signature_closer: a casual sign-off phrase
        """
        context = dict(lead)  # copy lead data

        # Time-of-day greeting
        context.setdefault("greeting", self._time_greeting())

        # Company compliment
        company = lead.get("company", "your company")
        context.setdefault("company_compliment", self._company_compliment(company))

        # Signature closer
        context.setdefault("signature_closer", self._signature_closer())

        return context

    @staticmethod
    def _time_greeting() -> str:
        """Return a greeting appropriate for the current time of day."""
        hour = datetime.now().hour
        if hour < 12:
            return "Good morning"
        elif hour < 17:
            return "Good afternoon"
        else:
            return "Good evening"

    @staticmethod
    def _company_compliment(company: str) -> str:
        """Return a randomized compliment mentioning the company."""
        compliments = [
            f"I've been following {company}'s growth and I'm impressed by what you're building",
            f"Love what {company} is doing in the space",
            f"I came across {company} recently and was really impressed",
            f"The work {company} is doing caught my attention",
            f"I've heard great things about the team at {company}",
        ]
        return random.choice(compliments)

    @staticmethod
    def _signature_closer() -> str:
        """Return a casual sign-off phrase."""
        closers = [
            "Best",
            "Cheers",
            "Thanks",
            "Talk soon",
            "Looking forward to hearing from you",
        ]
        return random.choice(closers)

    # ------------------------------------------------------------------
    # A/B testing
    # ------------------------------------------------------------------

    def generate_subject_variants(self, sequence_name: str, step: int,
                                  lead: dict, count: int = 3,
                                  seed: Optional[int] = None) -> list[str]:
        """Generate A/B variants of a subject line using spintax.

        Args:
            sequence_name: Name of the sequence.
            step: Step index.
            lead: Lead data for variable substitution.
            count: Number of variants to generate.
            seed: Optional RNG seed.

        Returns:
            List of unique rendered subject line variants.
        """
        if sequence_name not in self.sequences:
            raise KeyError(f"Sequence not found: {sequence_name}")

        seq = self.sequences[sequence_name]
        subject_template = seq["steps"][step]["subject"]
        context = self._build_context(lead)

        # Generate unique spintax resolutions
        spintax_variants = generate_variants(subject_template, count,
                                             unique=True, seed=seed)

        # Substitute variables in each variant
        results = []
        for variant in spintax_variants:
            def _replace(match, ctx=context):
                key = match.group(1)
                return str(ctx.get(key, match.group(0)))
            results.append(_VAR_PATTERN.sub(_replace, variant))

        return results

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_sequence(self, sequence_name: str,
                          required_vars: Optional[list[str]] = None) -> dict:
        """Validate that a sequence's templates contain the expected variables.

        Args:
            sequence_name: Name of the sequence to validate.
            required_vars: List of variable names that must appear in the
                           template. Defaults to ["first_name", "company"].

        Returns:
            Dict with 'valid' (bool), 'errors' (list of issue strings),
            and 'variables_found' (set of variable names found).
        """
        if required_vars is None:
            required_vars = ["first_name", "company"]

        if sequence_name not in self.sequences:
            return {"valid": False,
                    "errors": [f"Sequence '{sequence_name}' not found."],
                    "variables_found": set()}

        seq = self.sequences[sequence_name]
        steps = seq.get("steps", [])
        errors = []
        all_vars: set[str] = set()

        if not steps:
            errors.append("Sequence has no steps defined.")

        for i, step in enumerate(steps):
            if "subject" not in step:
                errors.append(f"Step {i} missing 'subject'.")
            if "body" not in step:
                errors.append(f"Step {i} missing 'body'.")

            # Collect all referenced variables
            text = step.get("subject", "") + " " + step.get("body", "")
            found = set(_VAR_PATTERN.findall(text))
            all_vars.update(found)

        # Check required variables are referenced somewhere
        for var in required_vars:
            if var not in all_vars:
                errors.append(
                    f"Required variable '{{{{{var}}}}}' not found in any step."
                )

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "variables_found": all_vars,
        }

    def validate_all(self, required_vars: Optional[list[str]] = None) -> dict:
        """Validate all loaded sequences.

        Returns:
            Dict mapping sequence name to its validation result.
        """
        return {
            name: self.validate_sequence(name, required_vars)
            for name in self.sequences
        }
