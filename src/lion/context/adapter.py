"""Context Adapter for cross-LLM formatting.

Different LLMs respond better to different context formats:
- Claude: structured with clear sections
- Gemini: flowing narrative text
- Ollama: compact, minimal overhead
"""

from .package import ContextPackage, ContextMode


class ContextAdapter:
    """Formats context packages for optimal comprehension per LLM."""

    def format(self, packages: list[ContextPackage],
               target_provider: str,
               mode: ContextMode) -> str:
        """Format context packages for a specific provider.

        Args:
            packages: List of ContextPackage objects to format
            target_provider: Name of the target LLM provider
            mode: The context mode (MINIMAL, STANDARD, RICH)

        Returns:
            Formatted string appropriate for the target provider
        """
        provider = target_provider.lower()

        if "claude" in provider:
            return self._format_structured(packages, mode)
        elif "gemini" in provider:
            return self._format_narrative(packages, mode)
        elif "ollama" in provider or "local" in provider:
            return self._format_compact(packages, mode)
        else:
            # Default to structured format
            return self._format_structured(packages, mode)

    def _format_structured(self, packages: list[ContextPackage],
                           mode: ContextMode) -> str:
        """Claude: structured with clear sections."""
        parts = []

        for pkg in packages:
            section = f"Agent {pkg.agent_id} ({pkg.model})"
            if pkg.confidence is not None:
                section += f" [confidence: {pkg.confidence}]"
            section += ":\n"
            # Truncate proposal to key content (reasoning/alternatives
            # are shown separately below)
            output = pkg.output[:800] if len(pkg.output) > 800 else pkg.output
            section += f"Proposal: {output}\n"

            if mode != ContextMode.MINIMAL:
                if pkg.reasoning:
                    section += f"Reasoning: {pkg.reasoning}\n"
                if pkg.alternatives:
                    section += "Rejected alternatives:\n"
                    for alt in pkg.alternatives:
                        section += f"  - {alt}\n"
                if pkg.uncertainties:
                    section += "Uncertainties:\n"
                    for unc in pkg.uncertainties:
                        section += f"  - {unc}\n"

            if mode == ContextMode.RICH:
                if pkg.assumptions:
                    section += "Assumptions:\n"
                    for asm in pkg.assumptions:
                        section += f"  - {asm}\n"
                if pkg.risks:
                    section += "Risks:\n"
                    for risk in pkg.risks:
                        section += f"  - {risk}\n"
                if pkg.questions_for_team:
                    section += "Questions:\n"
                    for q in pkg.questions_for_team:
                        section += f"  - {q}\n"
                if pkg.belief_state:
                    section += "Belief State:\n"
                    if pkg.belief_state.knows:
                        section += f"  Knows: {'; '.join(pkg.belief_state.knows)}\n"
                    if pkg.belief_state.believes:
                        section += f"  Believes: {'; '.join(pkg.belief_state.believes)}\n"
                    if pkg.belief_state.others_likely_missing:
                        section += f"  Others might miss: {'; '.join(pkg.belief_state.others_likely_missing)}\n"

            parts.append(section)

        return "\n---\n".join(parts)

    def _format_narrative(self, packages: list[ContextPackage],
                          mode: ContextMode) -> str:
        """Gemini: flowing narrative text."""
        parts = []

        for pkg in packages:
            text = f"Agent {pkg.agent_id} (using {pkg.model}"
            if pkg.confidence is not None:
                text += f", {int(pkg.confidence * 100)}% confident"
            output = pkg.output[:800] if len(pkg.output) > 800 else pkg.output
            text += f") proposed: {output}"

            if mode != ContextMode.MINIMAL:
                if pkg.reasoning:
                    text += f" Their reasoning: {pkg.reasoning}"
                if pkg.alternatives:
                    alt_text = "; ".join(pkg.alternatives)
                    text += f" They also considered but rejected: {alt_text}."
                if pkg.uncertainties:
                    unc_text = "; ".join(pkg.uncertainties)
                    text += f" They are uncertain about: {unc_text}."

            if mode == ContextMode.RICH:
                if pkg.assumptions:
                    asm_text = "; ".join(pkg.assumptions)
                    text += f" Key assumptions: {asm_text}."
                if pkg.risks:
                    risk_text = "; ".join(pkg.risks)
                    text += f" Identified risks: {risk_text}."
                if pkg.belief_state and pkg.belief_state.others_likely_missing:
                    miss_text = "; ".join(pkg.belief_state.others_likely_missing)
                    text += f" Things others might miss: {miss_text}."

            parts.append(text)

        return "\n\n".join(parts)

    def _format_compact(self, packages: list[ContextPackage],
                        mode: ContextMode) -> str:
        """Ollama: minimal, direct, no fluff."""
        parts = []

        for pkg in packages:
            text = f"[{pkg.agent_id}/{pkg.model}]"
            if pkg.confidence is not None:
                text += f" conf:{pkg.confidence}"
            output = pkg.output[:800] if len(pkg.output) > 800 else pkg.output
            text += f"\n{output}"

            if mode != ContextMode.MINIMAL and pkg.uncertainties:
                text += f"\nUNSURE: {'; '.join(pkg.uncertainties)}"

            if mode == ContextMode.RICH:
                if pkg.assumptions:
                    text += f"\nASSUMES: {'; '.join(pkg.assumptions[:2])}"
                if pkg.risks:
                    text += f"\nRISKS: {'; '.join(pkg.risks[:2])}"

            parts.append(text)

        return "\n---\n".join(parts)

    def format_for_critique(self, packages: list[ContextPackage],
                            excluding_agent: str,
                            target_provider: str,
                            mode: ContextMode) -> str:
        """Format other agents' proposals for critique phase.

        Args:
            packages: All context packages from propose phase
            excluding_agent: Agent ID to exclude (the one doing the critique)
            target_provider: Target LLM provider
            mode: Context mode

        Returns:
            Formatted string of other proposals
        """
        other_packages = [p for p in packages if p.agent_id != excluding_agent]
        return self.format(other_packages, target_provider, mode)
