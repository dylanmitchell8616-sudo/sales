"""Spintax parser utility for generating email text variants.

Spintax uses curly braces and pipes to define alternatives:
    {Hello|Hi|Hey} -> randomly picks one of "Hello", "Hi", or "Hey"

Nested spintax is supported:
    {Hello|{Hey|Hi} there} -> "Hello" or "Hey there" or "Hi there"
"""

import random
from typing import Optional


def resolve_spintax(text: str, rng: Optional[random.Random] = None) -> str:
    """Resolve all spintax expressions in a string, picking random variants.

    Args:
        text: Input string potentially containing spintax like {A|B|C}.
        rng: Optional random.Random instance for reproducible results.

    Returns:
        A string with all spintax expressions resolved to a single variant.

    Examples:
        >>> resolve_spintax("{Hello|Hi} world", random.Random(42))
        'Hi world'
    """
    if rng is None:
        rng = random.Random()

    return _resolve(text, rng)


def _resolve(text: str, rng: random.Random) -> str:
    """Internal recursive spintax resolver that handles nested expressions."""
    result = []
    i = 0
    length = len(text)

    while i < length:
        if text[i] == '{' and i + 1 < length and text[i + 1] == '{':
            # This is a {{variable}} template placeholder — pass through as-is.
            # Find the closing }}
            end = text.find('}}', i + 2)
            if end == -1:
                # No closing }}, treat as literal
                result.append(text[i])
                i += 1
            else:
                result.append(text[i:end + 2])
                i = end + 2
        elif text[i] == '{':
            # Spintax block — find the matching closing brace
            depth = 1
            start = i + 1
            i += 1
            while i < length and depth > 0:
                if text[i] == '{' and i + 1 < length and text[i + 1] == '{':
                    # Skip {{variable}} inside spintax options
                    end = text.find('}}', i + 2)
                    if end != -1:
                        i = end + 2
                        continue
                if text[i] == '{':
                    depth += 1
                elif text[i] == '}':
                    depth -= 1
                i += 1

            if depth != 0:
                # Unmatched brace; treat as literal text
                result.append('{')
                i = start
                continue

            # Extract the content between braces
            inner = text[start:i - 1]

            # Split on top-level pipes only (not pipes inside nested braces)
            options = _split_options(inner)

            # Pick a random option and recursively resolve any nested spintax
            chosen = rng.choice(options)
            result.append(_resolve(chosen, rng))
        else:
            result.append(text[i])
            i += 1

    return ''.join(result)


def _split_options(text: str) -> list[str]:
    """Split spintax content on top-level pipe characters.

    Pipes inside nested braces are not treated as separators.

    Args:
        text: The content between a matched pair of spintax braces.

    Returns:
        List of option strings.
    """
    options = []
    depth = 0
    current = []

    i = 0
    while i < len(text):
        char = text[i]
        if char == '{' and i + 1 < len(text) and text[i + 1] == '{':
            # Skip {{variable}} — find closing }}
            end = text.find('}}', i + 2)
            if end != -1:
                current.append(text[i:end + 2])
                i = end + 2
                continue
        if char == '{':
            depth += 1
            current.append(char)
        elif char == '}':
            depth -= 1
            current.append(char)
        elif char == '|' and depth == 0:
            options.append(''.join(current))
            current = []
        else:
            current.append(char)
        i += 1

    options.append(''.join(current))
    return options


def generate_variants(text: str, count: int, unique: bool = True,
                      seed: Optional[int] = None) -> list[str]:
    """Generate multiple resolved variants from a spintax string.

    Args:
        text: Spintax string to resolve.
        count: Number of variants to generate.
        unique: If True, attempt to return only unique variants.
                If fewer unique variants exist than requested, returns
                all unique variants found up to max_attempts.
        seed: Optional seed for reproducibility.

    Returns:
        List of resolved strings.
    """
    rng = random.Random(seed)
    variants = []
    seen = set()
    max_attempts = count * 20  # Cap attempts to avoid infinite loops
    attempts = 0

    while len(variants) < count and attempts < max_attempts:
        variant = resolve_spintax(text, rng)
        attempts += 1

        if unique:
            if variant not in seen:
                seen.add(variant)
                variants.append(variant)
        else:
            variants.append(variant)

    return variants


def count_possible_variants(text: str) -> int:
    """Estimate the total number of unique variants a spintax string can produce.

    Args:
        text: Spintax string.

    Returns:
        The combinatorial count of all possible resolutions.
    """
    return _count_variants(text)


def _count_variants(text: str) -> int:
    """Recursively count variants in a spintax string."""
    i = 0
    length = len(text)
    total = 1  # Multiplicative identity for segments

    while i < length:
        if text[i] == '{':
            depth = 1
            start = i + 1
            i += 1
            while i < length and depth > 0:
                if text[i] == '{':
                    depth += 1
                elif text[i] == '}':
                    depth -= 1
                i += 1

            if depth != 0:
                continue

            inner = text[start:i - 1]
            options = _split_options(inner)

            # Sum the variant counts of each option
            option_count = sum(_count_variants(opt) for opt in options)
            total *= option_count
        else:
            i += 1

    return total
