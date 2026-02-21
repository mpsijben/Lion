"""Parsing logic for structured agent output."""

import re
from .package import ContextPackage, ContextMode, BeliefState


def parse_context_package(raw_output: str, agent_id: str, model: str,
                          mode: ContextMode) -> ContextPackage:
    """Parse structured agent output into a ContextPackage.

    The parser is lenient: if structured output fails, it gracefully falls
    back to treating the entire output as the `output` field.
    """
    pkg = ContextPackage(
        output=raw_output,
        agent_id=agent_id,
        model=model,
    )

    if mode == ContextMode.MINIMAL:
        return pkg

    # Extract sections using ## headers
    sections = extract_sections(raw_output)

    # Standard fields - if "approach" section exists, use it as output
    if sections.get("approach"):
        pkg.output = sections.get("approach", raw_output)

    pkg.reasoning = sections.get("reasoning")
    pkg.alternatives = parse_list(sections.get("alternatives considered", ""))
    pkg.uncertainties = parse_list(sections.get("uncertainties", ""))
    pkg.confidence = parse_confidence(sections.get("confidence", "0.5"))

    # Rich fields
    if mode == ContextMode.RICH:
        pkg.assumptions = parse_list(sections.get("assumptions", ""))
        pkg.risks = parse_list(sections.get("risks", ""))
        pkg.questions_for_team = parse_list(sections.get("questions", ""))
        pkg.files_examined = parse_list(sections.get("files examined", ""))
        pkg.dependencies = parse_list(sections.get("dependencies", ""))

        # Belief State parsing
        knows = parse_list(sections.get("what you know", ""))
        believes = parse_list(sections.get("what you believe but didn't verify", ""))
        others = parse_list(sections.get("what others might miss", ""))

        if knows or believes or others:
            pkg.belief_state = BeliefState(
                knows=knows,
                believes=believes,
                others_likely_missing=others
            )

    return pkg


def extract_sections(text: str) -> dict:
    """Extract content under ## headers.

    Handles variations like:
    - ## Header
    - ##Header
    - ## Header:
    """
    sections = {}
    current_header = None
    current_content = []

    for line in text.split('\n'):
        stripped = line.strip()
        # Match ## headers (with optional leading spaces)
        if stripped.startswith('## ') or stripped.startswith('##'):
            # Save previous section
            if current_header:
                sections[current_header] = '\n'.join(current_content).strip()

            # Extract new header name
            header_text = stripped.lstrip('#').strip()
            # Remove trailing colon if present
            header_text = header_text.rstrip(':').strip()
            current_header = header_text.lower()
            current_content = []
        else:
            current_content.append(line)

    # Save last section
    if current_header:
        sections[current_header] = '\n'.join(current_content).strip()

    return sections


def parse_list(text: str) -> list[str]:
    """Parse markdown list items.

    Handles variations like:
    - Item
    * Item
    1. Item
    - **Item**: description
    """
    if not text:
        return []

    items = []
    for line in text.split('\n'):
        line = line.strip()
        # Match bullet points: -, *, or numbered lists
        if line.startswith('- ') or line.startswith('* '):
            items.append(line[2:].strip())
        elif re.match(r'^\d+\.\s+', line):
            # Numbered list
            item = re.sub(r'^\d+\.\s+', '', line)
            items.append(item.strip())

    return items


def parse_confidence(text: str) -> float:
    """Extract a confidence score from text.

    Handles:
    - 0.7
    - 0.7/1.0
    - 70%
    - 7/10
    - "moderate" (0.5), "high" (0.8), "low" (0.3)
    """
    if not text:
        return 0.5

    text_lower = text.lower().strip()

    # Handle word-based confidence
    if "very high" in text_lower:
        return 0.9
    elif "high" in text_lower:
        return 0.8
    elif "moderate" in text_lower or "medium" in text_lower:
        return 0.5
    elif "low" in text_lower:
        return 0.3
    elif "very low" in text_lower:
        return 0.1

    # Try to find numeric values
    try:
        # Match percentage (70%)
        pct_match = re.search(r'(\d+)\s*%', text)
        if pct_match:
            return min(1.0, max(0.0, int(pct_match.group(1)) / 100))

        # Match fraction (7/10)
        frac_match = re.search(r'(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)', text)
        if frac_match:
            num = float(frac_match.group(1))
            denom = float(frac_match.group(2))
            if denom > 0:
                return min(1.0, max(0.0, num / denom))

        # Match decimal (0.7)
        numbers = re.findall(r'([01]\.?\d*)', text)
        if numbers:
            return min(1.0, max(0.0, float(numbers[0])))

    except (ValueError, IndexError):
        pass

    return 0.5  # Default


def estimate_tokens(text: str) -> int:
    """Rough token estimate for text (words * 1.3)."""
    if not text:
        return 0
    return int(len(text.split()) * 1.3)
