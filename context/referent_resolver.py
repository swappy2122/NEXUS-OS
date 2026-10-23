"""Referent resolver for NEXUS OS.

Detects deictic pronouns and demonstratives in user intent text
(\"this\", \"it\", \"that\", etc.) and resolves them to concrete entities
using the :class:`~context.environment.EnvironmentContext`.

The resolver is designed to be called by the Supervisor *before*
intent classification, so that the routing strategy receives a
de-ambiguated intent string.

Usage::

    resolver = ReferentResolver(env_context)
    result = resolver.resolve("close this")
    # result.resolved_intent == "close Firefox"
    # result.referents == [Referent(pronoun="this", resolved="Firefox", ...)]
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from context.environment import EnvironmentContext

logger = logging.getLogger("nexus.context.referent")


# ── Data models ──────────────────────────────────────────────────────────

@dataclass
class Referent:
    """A single resolved pronoun occurrence.

    Attributes:
        pronoun:       The original pronoun text (e.g. ``"this"``).
        resolved:      What it was resolved to (e.g. ``"Firefox"``).
        subject_type:  Kind of entity (``"app"``, ``"window"``, ``"file"``).
        source:        Where the resolution came from
                       (``"focused_window"``, ``"action_history[0]"``, …).
        confidence:    How confident the resolution is (0.0–1.0).
    """

    pronoun: str = ""
    resolved: str = ""
    subject_type: str = ""
    source: str = ""
    confidence: float = 0.0


@dataclass
class ResolutionResult:
    """The outcome of resolving all pronouns in a user intent.

    Attributes:
        original_intent:  The user's raw input text.
        resolved_intent:  Intent with pronouns replaced by resolved names.
        referents:        List of all resolved (or attempted) referents.
        has_unresolved:   True if any pronoun could not be resolved.
    """

    original_intent: str = ""
    resolved_intent: str = ""
    referents: list[Referent] = field(default_factory=list)
    has_unresolved: bool = False


# ── Pronoun patterns ─────────────────────────────────────────────────────

# Patterns that capture deictic pronouns in common OS-command positions.
# Each pattern group is (full_match, pronoun, optional_context_hint).
_PRONOUN_PATTERNS: list[tuple[re.Pattern[str], str | None]] = [
    # "close this", "open it", "move that"
    (re.compile(
        r"\b(this|that|it)\b(?!\s+(is|was|has|does|should|would|could|can|will|might|may|isn't|doesn't))",
        re.IGNORECASE,
    ), None),
]

# Contextual hints derived from the surrounding verb / phrase.
_VERB_HINTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(close|quit|kill|stop|minimize|maximize|resize|move)\b", re.IGNORECASE), "app"),
    (re.compile(r"\b(focus|switch\s+to|bring\s+up|activate)\b", re.IGNORECASE), "window"),
    (re.compile(r"\b(open|launch|start|run)\b", re.IGNORECASE), "app"),
    (re.compile(r"\b(read|write|edit|delete|copy|move|rename)\s+(this|that|it)\s+(file|folder|document)\b", re.IGNORECASE), "file"),
    (re.compile(r"\b(read|edit|delete|copy|rename)\b", re.IGNORECASE), "file"),
]


# ── Resolver ─────────────────────────────────────────────────────────────

class ReferentResolver:
    """Detects and resolves pronouns in user intent text.

    Parameters:
        environment: The environment context providing desktop state.
    """

    def __init__(self, environment: EnvironmentContext) -> None:
        self._env = environment

    def resolve(self, intent: str) -> ResolutionResult:
        """Resolve all deictic pronouns in *intent*.

        Returns a :class:`ResolutionResult` with the rewritten intent
        and details of each referent.  If a pronoun cannot be resolved,
        it is left as-is in the output and ``has_unresolved`` is set.
        """
        result = ResolutionResult(original_intent=intent)
        resolved_text = intent
        has_unresolved = False

        # Find all pronoun occurrences
        for pattern, _ in _PRONOUN_PATTERNS:
            for match in pattern.finditer(intent):
                pronoun = match.group(1).lower()
                hint = self._infer_subject_hint(intent)

                referent_data = self._env.resolve_referent(
                    pronoun, subject_type_hint=hint,
                )

                if referent_data:
                    subject = referent_data["subject"]
                    ref = Referent(
                        pronoun=pronoun,
                        resolved=subject,
                        subject_type=referent_data.get("subject_type", ""),
                        source=referent_data.get("source", ""),
                        confidence=0.9 if hint else 0.7,
                    )
                    result.referents.append(ref)

                    # Replace the pronoun in the intent text
                    resolved_text = _replace_first(
                        resolved_text, match.group(1), subject,
                    )

                    logger.info(
                        "Resolved '%s' → '%s' (type=%s, source=%s)",
                        pronoun, subject, ref.subject_type, ref.source,
                    )
                else:
                    ref = Referent(
                        pronoun=pronoun,
                        resolved="",
                        confidence=0.0,
                    )
                    result.referents.append(ref)
                    has_unresolved = True
                    logger.debug(
                        "Could not resolve pronoun '%s' in: %.80s",
                        pronoun, intent,
                    )
                # Only resolve the first pronoun occurrence per pattern pass
                break

        result.resolved_intent = resolved_text
        result.has_unresolved = has_unresolved
        return result

    def has_pronouns(self, intent: str) -> bool:
        """Quick check for whether *intent* contains resolvable pronouns."""
        for pattern, _ in _PRONOUN_PATTERNS:
            if pattern.search(intent):
                return True
        return False

    @staticmethod
    def _infer_subject_hint(intent: str) -> str | None:
        """Try to infer what kind of entity the user is referring to."""
        for pattern, hint in _VERB_HINTS:
            if pattern.search(intent):
                return hint
        return None


# ── Helpers ──────────────────────────────────────────────────────────────

def _replace_first(text: str, target: str, replacement: str) -> str:
    """Replace the first case-insensitive occurrence of *target*."""
    pattern = re.compile(re.escape(target), re.IGNORECASE)
    return pattern.sub(replacement, text, count=1)
