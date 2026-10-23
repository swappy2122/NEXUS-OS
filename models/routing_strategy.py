"""Model routing strategies for NEXUS OS.

A ``ModelRoutingStrategy`` inspects an incoming request and decides:
  1. What **category** of task it is (OS command, coding, reasoning …).
  2. How **complex** it is (bypass, light, standard, heavy).
  3. Optionally, a pre-built response if no LLM call is needed.

Included strategies
───────────────────
* **DefaultPassthroughStrategy** — always returns ``STANDARD`` tier.
  Replicates pre-router behaviour: every request hits the default backend.
* **RuleBasedStrategy** — keyword + heuristic classification.
  Identifies simple OS commands for ``BYPASS``, estimates complexity for
  everything else.  No external dependencies.

The ``ModelRoutingStrategy`` protocol is intentionally separate from the
Supervisor's ``RoutingStrategy`` (which picks *agents*).  This one picks
*models / backends*.
"""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from typing import Any

from models.routing_types import (
    ComplexityTier,
    ModelTierConfig,
    RoutingDecision,
    TaskCategory,
)

logger = logging.getLogger("nexus.models.routing_strategy")


# ── Strategy interface ────────────────────────────────────────────────────

class ModelRoutingStrategy(ABC):
    """Interface for model-level routing strategies.

    Implementations classify a chat request and return a
    :class:`RoutingDecision` that the :class:`~models.router.ModelRouter`
    uses to select a backend (or skip the LLM entirely).
    """

    @abstractmethod
    def classify(
        self,
        messages: list[dict[str, Any]],
        *,
        agent_role: str = "*",
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> RoutingDecision:
        """Analyse the request and return a routing decision.

        Parameters:
            messages:   OpenAI-style message list.
            agent_role: The role of the calling agent (e.g. ``"file"``).
            tools:      Tool schemas available to the backend.
            **kwargs:   Extra context the strategy may use.
        """
        ...


# ── Default passthrough (backward-compatible) ────────────────────────────

class DefaultPassthroughStrategy(ModelRoutingStrategy):
    """Always routes to the ``STANDARD`` tier.

    This replicates the pre-router behaviour where every request is
    forwarded to the resolved backend without classification.
    """

    def classify(
        self,
        messages: list[dict[str, Any]],
        *,
        agent_role: str = "*",
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> RoutingDecision:
        return RoutingDecision(
            category=TaskCategory.UNKNOWN,
            tier=ComplexityTier.STANDARD,
            reason="passthrough — no classification applied",
        )


# ── Rule-based strategy ─────────────────────────────────────────────────

# Patterns that indicate simple, deterministic OS operations.
# These are matched against the *last user message* content.
_SIMPLE_OS_PATTERNS: list[re.Pattern[str]] = [
    # File operations
    re.compile(
        r"^(list|ls|show|display|get)\s+(files?|folders?|dir(?:ector(?:y|ies))?|contents?)",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(create|make|mkdir|touch|new)\s+(a\s+)?(file|folder|dir(?:ectory)?)",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(read|cat|open|view|show)\s+(the\s+)?(file|contents?\s+of)",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(delete|remove|rm|rmdir)\s+(the\s+)?(file|folder|dir(?:ectory)?)",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(move|mv|rename|copy|cp)\s+",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(search|find|locate)\s+(for\s+)?(files?|folders?)",
        re.IGNORECASE,
    ),
    # System info
    re.compile(
        r"^(show|get|check|what(?:'s| is))\s+(the\s+)?(cpu|memory|ram|disk|storage|system\s+info|os\s+info|uptime|processes)",
        re.IGNORECASE,
    ),
    # App management
    re.compile(
        r"^(open|launch|start|run)\s+(the\s+)?(\w+)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(close|quit|kill|stop)\s+(the\s+)?(\w+)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(list|show)\s+(running|installed|active)\s+(apps?|programs?|processes)",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(is)\s+(\w+)\s+(running|open|active)",
        re.IGNORECASE,
    ),
]

# Patterns for coding tasks
_CODING_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"\b(write|generate|create|build|implement|refactor|debug|fix)\s+"
        r"(a\s+|the\s+|some\s+)?(code|function|class|script|program|module|api|endpoint)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(python|javascript|typescript|rust|go|java|c\+\+|html|css|sql|bash)\b.*\b(code|script|function|snippet)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(syntax\s+error|stack\s*trace|exception|bug|traceback)\b", re.IGNORECASE),
    re.compile(r"```", re.IGNORECASE),  # fenced code block in message
]

# Patterns for vision tasks
_VISION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"\b(look\s+at|analyse|analyze|describe|identify|recognize|detect|what\s+is\s+in)\b"
        r".*\b(image|photo|picture|screenshot|screen|camera|frame|video)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(ocr|read\s+text\s+from|extract\s+from)\s+(the\s+)?(image|screen)", re.IGNORECASE),
]

# Heuristic thresholds for complexity within non-bypass categories
_HEAVY_WORD_COUNT = 200       # user message word count suggesting complex context
_HEAVY_MESSAGE_COUNT = 15     # long conversation history
_LIGHT_WORD_COUNT = 20        # short, simple question


class RuleBasedStrategy(ModelRoutingStrategy):
    """Keyword + heuristic classification strategy.

    Classification flow:

    1. Check if the latest user message matches simple OS command patterns.
       If so → ``TaskCategory.SIMPLE_OS_COMMAND`` + ``ComplexityTier.BYPASS``.
    2. Check for coding / vision / speech patterns → appropriate category.
    3. Estimate complexity from message length, conversation depth, and
       keyword signals → ``LIGHT``, ``STANDARD``, or ``HEAVY``.
    """

    def __init__(self, tier_config: ModelTierConfig | None = None) -> None:
        self._tier_config = tier_config or ModelTierConfig()

    def classify(
        self,
        messages: list[dict[str, Any]],
        *,
        agent_role: str = "*",
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> RoutingDecision:
        user_content = _last_user_content(messages)

        if not user_content:
            return RoutingDecision(
                category=TaskCategory.UNKNOWN,
                tier=ComplexityTier.STANDARD,
                reason="no user content found — defaulting to standard",
            )

        # ── 1. Simple OS commands → BYPASS ──────────────────────────────
        if self._is_simple_os_command(user_content, agent_role):
            logger.debug("Classified as SIMPLE_OS_COMMAND (BYPASS): %.80s", user_content)
            return RoutingDecision(
                category=TaskCategory.SIMPLE_OS_COMMAND,
                tier=ComplexityTier.BYPASS,
                reason=f"deterministic OS operation detected (agent_role={agent_role})",
                metadata={"matched_agent_role": agent_role},
            )

        # ── 2. Vision tasks ─────────────────────────────────────────────
        if self._matches_patterns(user_content, _VISION_PATTERNS):
            tier = self._estimate_complexity(user_content, messages, floor=ComplexityTier.STANDARD)
            logger.debug("Classified as VISION (%s): %.80s", tier, user_content)
            return RoutingDecision(
                category=TaskCategory.VISION,
                tier=tier,
                reason="vision/spatial keywords detected",
            )

        # ── 3. Coding tasks ─────────────────────────────────────────────
        if self._matches_patterns(user_content, _CODING_PATTERNS):
            tier = self._estimate_complexity(user_content, messages, floor=ComplexityTier.STANDARD)
            logger.debug("Classified as CODING (%s): %.80s", tier, user_content)
            return RoutingDecision(
                category=TaskCategory.CODING,
                tier=tier,
                reason="coding keywords detected",
            )

        # ── 4. General reasoning (default) ───────────────────────────────
        tier = self._estimate_complexity(user_content, messages)
        logger.debug("Classified as GENERAL_REASONING (%s): %.80s", tier, user_content)
        return RoutingDecision(
            category=TaskCategory.GENERAL_REASONING,
            tier=tier,
            reason="general reasoning — complexity estimated from message heuristics",
        )

    # -- internal helpers -------------------------------------------------

    @staticmethod
    def _is_simple_os_command(content: str, agent_role: str) -> bool:
        """Return True if the content looks like a deterministic OS operation.

        Two signals must align:
        1. The agent role is one that handles OS operations (file, system, app)
           **or** the wildcard ``*`` (supervisor will pick the right agent).
        2. The content matches at least one simple-OS regex pattern.
        """
        os_roles = {"file", "system", "app", "*", "supervisor"}
        if agent_role not in os_roles:
            return False
        return any(p.search(content) for p in _SIMPLE_OS_PATTERNS)

    @staticmethod
    def _matches_patterns(content: str, patterns: list[re.Pattern[str]]) -> bool:
        return any(p.search(content) for p in patterns)

    @staticmethod
    def _estimate_complexity(
        content: str,
        messages: list[dict[str, Any]],
        floor: ComplexityTier = ComplexityTier.LIGHT,
    ) -> ComplexityTier:
        """Heuristic complexity estimation.

        Factors:
        - Word count of the latest user message.
        - Total number of messages (conversation depth).
        - Presence of certain complexity indicators.
        """
        word_count = len(content.split())
        msg_count = len(messages)

        # Heavy indicators
        heavy_signals = [
            word_count >= _HEAVY_WORD_COUNT,
            msg_count >= _HEAVY_MESSAGE_COUNT,
            bool(re.search(r"\b(step[- ]by[- ]step|detailed|comprehensive|thorough|in[- ]depth)\b", content, re.IGNORECASE)),
            bool(re.search(r"\b(compare|contrast|evaluate|trade-?offs?|pros?\s+and\s+cons?)\b", content, re.IGNORECASE)),
        ]
        if sum(heavy_signals) >= 2:
            return ComplexityTier.HEAVY

        # Light — very short, simple question, no deep history
        if word_count <= _LIGHT_WORD_COUNT and msg_count <= 4:
            return max_tier(floor, ComplexityTier.LIGHT)

        # Standard
        return max_tier(floor, ComplexityTier.STANDARD)


# ── Utility helpers ──────────────────────────────────────────────────────

def _last_user_content(messages: list[dict[str, Any]]) -> str:
    """Extract the text content of the most recent user message."""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, str):
                return content.strip()
            # Handle list-style content (vision messages, etc.)
            if isinstance(content, list):
                parts = [p.get("text", "") for p in content if p.get("type") == "text"]
                return " ".join(parts).strip()
    return ""


# Tier ordering for floor enforcement
_TIER_ORDER = {
    ComplexityTier.BYPASS: 0,
    ComplexityTier.LIGHT: 1,
    ComplexityTier.STANDARD: 2,
    ComplexityTier.HEAVY: 3,
}


def max_tier(a: ComplexityTier, b: ComplexityTier) -> ComplexityTier:
    """Return whichever tier is higher (more powerful)."""
    return a if _TIER_ORDER[a] >= _TIER_ORDER[b] else b
