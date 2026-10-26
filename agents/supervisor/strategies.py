"""Routing strategies for intent classification.

A ``RoutingStrategy`` inspects a user's natural-language intent and
decides which agent(s) should handle it.  The Supervisor delegates this
decision to whatever strategy is injected at construction time.

Included strategies
───────────────────
* **KeywordRoutingStrategy**    — fast, deterministic, no LLM required.
  Preserves the exact keyword-scoring logic from the v0.1 Supervisor.
* **CapabilityRoutingStrategy** — matches intent words against declared
  agent capabilities.
* **LLMRoutingStrategy**        — uses an LLM for classification and
  multi-agent decomposition.  Falls back to a secondary strategy on
  failure.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

from agents.supervisor.types import (
    IntentClassification,
    StructuredAction,
    SubIntent,
)

logger = logging.getLogger("nexus.supervisor.routing")


# ── Agent metadata visible to strategies ─────────────────────────────────

class AgentMeta(BaseModel):
    """Lightweight descriptor of an available agent.

    Built by the Supervisor from ``AgentRegistry`` contents and passed
    to the routing strategy.  Strategies should never need to import
    or reference live agent instances.
    """

    name: str
    description: str = ""
    capabilities: list[str] = []


# ── Strategy protocol ───────────────────────────────────────────────────

@runtime_checkable
class RoutingStrategy(Protocol):
    """Interface that all routing strategies must satisfy.

    Implementations receive the raw user intent, a list of available
    agents, and optional conversation history, returning an
    ``IntentClassification`` describing which agent(s) to use and
    any concrete structured actions.
    """

    async def classify(
        self,
        intent: str,
        available_agents: list[AgentMeta],
        conversation_history: list[dict[str, str]] | None = None,
        **kwargs: Any,
    ) -> IntentClassification: ...


# ═══════════════════════════════════════════════════════════════════════════
# Keyword-based routing (v0.1 prototype, preserved)
# ═══════════════════════════════════════════════════════════════════════════

DEFAULT_KEYWORDS: dict[str, list[str]] = {
    "file_agent": [
        "file", "read", "write", "create", "delete", "search",
        "find", "list", "directory", "folder", "open", "save",
        "copy", "move", "rename", "path",
    ],
    "system_agent": [
        "system", "process", "cpu", "memory", "disk", "uptime",
        "install", "package", "run", "command", "execute", "shell",
        "terminal", "apt", "pip", "status", "monitor", "info",
    ],
    "app_agent": [
        "app", "application", "launch", "close app", "open app",
        "kill app", "running apps", "installed apps", "software",
        "program", "start app", "stop app", "quit app", "exit app",
        "running", "is running", "is app running",
        "firefox", "chrome", "vlc", "calculator",
        "open firefox", "launch firefox",
        "open files", "open file manager", "files", "file manager",
        "open downloads", "downloads",
        "open documents", "documents",
        "open home",
    ],
    # ── Future agents (keywords ready, activate by registering the agent) ──
    "window_agent": [
        "window", "minimize", "maximize", "resize", "arrange",
        "tile", "snap", "focus window", "switch window",
    ],
    "workspace_agent": [
        "workspace", "virtual desktop", "desktop", "switch workspace",
    ],
    "voice_agent": [
        "voice", "speak", "say", "dictate", "transcribe", "listen",
    ],
    "vision_agent": [
        "look", "see", "recognize", "identify", "spatial",
        "ar", "vr", "3d", "overlay",
    ],
}


class KeywordRoutingStrategy:
    """Deterministic keyword-scoring strategy.

    Scores each agent by counting how many of its keywords appear in
    the intent string (substring match).  Picks the highest scorer
    **that is actually registered**.

    This is the same logic the v0.1 Supervisor used, extracted into a
    pluggable strategy so it can be replaced with LLM classification.

    Parameters:
        keywords: Agent-name → keyword-list mapping.  Defaults to
                  ``DEFAULT_KEYWORDS`` which includes all current and
                  future agents.
    """

    def __init__(
        self,
        keywords: dict[str, list[str]] | None = None,
    ) -> None:
        self._keywords = keywords or DEFAULT_KEYWORDS

    async def classify(
        self,
        intent: str,
        available_agents: list[AgentMeta],
        conversation_history: list[dict[str, str]] | None = None,
        **kwargs: Any,
    ) -> IntentClassification:
        intent_lower = intent.lower()
        available_names = {a.name for a in available_agents}

        # Score every agent (weighted by keyword length to favor specific matches)
        scores: dict[str, int] = {}
        for agent_name, kws in self._keywords.items():
            score = sum(len(kw) for kw in kws if kw in intent_lower)
            if score > 0:
                scores[agent_name] = score

        if not scores:
            return IntentClassification(
                raw_intent=intent,
                metadata={"strategy": "keyword"},
            )

        # Pick the best agent that is actually registered
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        primary: str | None = None
        for name, _ in ranked:
            if name in available_names:
                primary = name
                break

        best_score = ranked[0][1] if ranked else 0
        max_possible = max(
            (len(kws) for kws in self._keywords.values()),
            default=1,
        )
        confidence = min(best_score / max_possible, 1.0)

        # Multi-agent decomposition for coordinating conjunctions (and, then, after)
        sub_intents: list[SubIntent] = []
        is_sequential = bool(re.search(r'\b(?:then|after that|after)\b', intent_lower))
        conjunction_split = re.split(r'\b(?:and|then|after that|after)\b', intent, flags=re.IGNORECASE)

        if len(conjunction_split) >= 2:
            agent_matches = []
            for part in conjunction_split:
                part_clean = part.strip()
                if not part_clean:
                    continue
                part_lower = part_clean.lower()
                part_scores: dict[str, int] = {}
                for a_name in available_names:
                    kws = self._keywords.get(a_name, [])
                    s = sum(1 for kw in kws if kw in part_lower)
                    if s > 0:
                        part_scores[a_name] = s
                if part_scores:
                    best_agent = max(part_scores.items(), key=lambda kv: kv[1])[0]
                    agent_matches.append((best_agent, part_clean))

            if len(agent_matches) >= 2 and len({a for a, _ in agent_matches}) > 1:
                for idx, (ag, desc) in enumerate(agent_matches):
                    deps = [idx - 1] if (is_sequential and idx > 0) else []
                    sub_intents.append(
                        SubIntent(
                            target_agent=ag,
                            description=desc,
                            depends_on=deps,
                        )
                    )

        requires_multi = len(sub_intents) >= 2

        return IntentClassification(
            raw_intent=intent,
            primary_agent=primary,
            agent_scores={k: float(v) for k, v in scores.items()},
            confidence=confidence,
            requires_multi_agent=requires_multi,
            sub_intents=sub_intents,
            metadata={"strategy": "keyword"},
        )


# ═══════════════════════════════════════════════════════════════════════════
# Capability-based routing
# ═══════════════════════════════════════════════════════════════════════════

class CapabilityRoutingStrategy:
    """Routes by matching intent words against declared capability names.

    Each agent's capability names are split on underscores into
    constituent words (e.g. ``file_read`` → ``["file", "read"]``), and
    a score is incremented for each word found in the intent.

    Best used as a secondary/fallback strategy or when agents have
    richly described capabilities.
    """

    async def classify(
        self,
        intent: str,
        available_agents: list[AgentMeta],
        conversation_history: list[dict[str, str]] | None = None,
        **kwargs: Any,
    ) -> IntentClassification:
        intent_lower = intent.lower()
        scores: dict[str, int] = {}

        for agent in available_agents:
            score = 0
            for cap in agent.capabilities:
                cap_parts = cap.lower().replace("_", " ").split()
                score += sum(1 for part in cap_parts if part in intent_lower)
            if score > 0:
                scores[agent.name] = score

        if not scores:
            return IntentClassification(
                raw_intent=intent,
                metadata={"strategy": "capability"},
            )

        best = max(scores, key=scores.get)  # type: ignore[arg-type]
        best_score = scores[best]
        total_caps = sum(len(a.capabilities) for a in available_agents) or 1

        return IntentClassification(
            raw_intent=intent,
            primary_agent=best,
            agent_scores={k: float(v) for k, v in scores.items()},
            confidence=min(best_score / total_caps, 1.0),
            metadata={"strategy": "capability"},
        )


# ═══════════════════════════════════════════════════════════════════════════
# LLM-based routing (future-ready)
# ═══════════════════════════════════════════════════════════════════════════

class LLMRoutingStrategy:
    """Uses an LLM to understand natural language intent, identify required
    capabilities, produce structured actions/tool calls, and coordinate multi-step tasks.

    Architecture:
        User → Supervisor → LLM → structured action → Agent → Tool → Linux

    Safety:
        - The LLM does NOT receive unrestricted shell access.
        - Validates all structured actions against capability boundaries, schema contracts,
          and dangerous command patterns prior to execution.
        - Falls back gracefully to a secondary strategy on LLM failure.

    Parameters:
        llm:            Any object satisfying the ``LLMProvider`` protocol.
        agent_registry: Optional registry for live tool introspection.
        validator:      Optional ActionValidator for pre-execution verification.
        fallback:       Fallback strategy when LLM fails (default: KeywordRoutingStrategy).
        max_history:    Maximum conversation history messages to pass (minimal tokens).
    """

    SUPERVISOR_SYSTEM_PROMPT = """\
You are the NEXUS OS Supervisor Orchestrator.
Understand the user's natural language request, identify required capabilities, and plan structured tool actions.

Agents & Available Tools:
{tools_catalog}

Rules:
1. Choose the minimal, most appropriate agent and tool for the task.
2. For multi-step tasks, provide actions in execution order and set "depends_on" with indices of prerequisite actions (0-based).
3. If actions are independent, set "depends_on": [] to allow parallel execution.
4. You do NOT have unrestricted shell access. Destructive shell commands (e.g. deleting root, fork bombs, raw disk writes) are strictly forbidden.
5. If the user request is conversational or needs no tool, leave "actions" empty and provide a helpful "direct_response".

Respond with a JSON object matching this schema:
{{
  "thought": "<brief reasoning identifying user intent and capabilities>",
  "capabilities_required": ["<capability_name>"],
  "actions": [
    {{
      "agent_name": "<agent_name>",
      "tool_name": "<tool_name>",
      "arguments": {{"<arg_key>": "<arg_val>"}},
      "depends_on": []
    }}
  ],
  "direct_response": "<optional direct text response if no tools are needed>"
}}
Return ONLY valid JSON.
"""

    def __init__(
        self,
        llm: Any,
        agent_registry: Any = None,
        validator: Any = None,
        fallback: RoutingStrategy | None = None,
        max_history: int = 6,
    ) -> None:
        self._llm = llm
        self._registry = agent_registry
        self._validator = validator
        self._fallback: RoutingStrategy = fallback or KeywordRoutingStrategy()
        self._max_history = max_history

    def _build_tools_catalog(self, available_agents: list[AgentMeta]) -> str:
        """Construct a minimal-token catalog of agents and their tools."""
        catalog_lines = []
        if self._registry:
            for agent in self._registry:
                tool_summaries = []
                for t in agent.tools.values():
                    props = list((t.parameters_schema or {}).get("properties", {}).keys())
                    param_sig = f"({', '.join(props)})" if props else "()"
                    tool_summaries.append(f"{t.name}{param_sig}")
                catalog_lines.append(f"- {agent.name}: {', '.join(tool_summaries)}")
        else:
            for a in available_agents:
                catalog_lines.append(f"- {a.name}: {', '.join(a.capabilities)}")
        return "\n".join(catalog_lines)

    async def classify(
        self,
        intent: str,
        available_agents: list[AgentMeta],
        conversation_history: list[dict[str, str]] | None = None,
        **kwargs: Any,
    ) -> IntentClassification:
        tools_catalog = self._build_tools_catalog(available_agents)
        system_msg = self.SUPERVISOR_SYSTEM_PROMPT.format(tools_catalog=tools_catalog)

        # Build bounded chat messages for minimal token usage with conversation support
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_msg},
        ]
        if conversation_history:
            recent_history = conversation_history[-self._max_history:]
            for msg in recent_history:
                if msg.get("role") in ("user", "assistant") and msg.get("content"):
                    messages.append({"role": msg["role"], "content": msg["content"]})

        messages.append({"role": "user", "content": intent})

        # Collect tool schemas for models supporting function-calling
        tool_schemas: list[dict[str, Any]] = []
        if self._registry:
            for agent in self._registry:
                for tool in agent.tools.values():
                    if hasattr(tool, "to_llm_schema"):
                        tool_schemas.append(tool.to_llm_schema())

        try:
            response = await self._llm.chat(messages=messages, tools=tool_schemas or None)
            available_names = {a.name for a in available_agents}
            content = (response.content or "").strip()

            actions: list[StructuredAction] = []
            thought = ""
            direct_response = ""

            # Check if intent implies sequential steps
            is_sequential = bool(re.search(r'\b(?:then|after that|after)\b', intent, flags=re.IGNORECASE))

            # Check if LLM returned native tool_calls
            if response.tool_calls:
                for idx, tc in enumerate(response.tool_calls):
                    t_name = tc.get("name", "")
                    t_args = tc.get("arguments", {})
                    owning_agent = self._find_owning_agent(t_name, available_agents)
                    if owning_agent:
                        deps = [idx - 1] if (is_sequential and idx > 0) else []
                        actions.append(
                            StructuredAction(
                                step_id=idx,
                                agent_name=owning_agent,
                                tool_name=t_name,
                                arguments=t_args,
                                depends_on=deps,
                                thought=f"Call tool {t_name}",
                            )
                        )

            # Otherwise attempt parsing JSON output
            elif content:
                clean_json = content
                if clean_json.startswith("```"):
                    clean_json = re.sub(r"^```(?:json)?\n?", "", clean_json)
                    clean_json = re.sub(r"\n?```$", "", clean_json)
                clean_json = clean_json.strip()

                try:
                    parsed = json.loads(clean_json)
                    if isinstance(parsed, dict):
                        thought = parsed.get("thought", "")
                        direct_response = parsed.get("direct_response", "")

                        # Handle actions list
                        raw_actions = parsed.get("actions", [])
                        for idx, ra in enumerate(raw_actions):
                            ag = ra.get("agent_name", "")
                            t_name = ra.get("tool_name", "")
                            if not ag and t_name:
                                ag = self._find_owning_agent(t_name, available_agents) or ""
                            if ag in available_names:
                                actions.append(
                                    StructuredAction(
                                        step_id=ra.get("step_id", idx),
                                        agent_name=ag,
                                        tool_name=t_name,
                                        arguments=ra.get("arguments", {}),
                                        depends_on=ra.get("depends_on", []),
                                        thought=ra.get("thought", thought),
                                    )
                                )

                        # Backward-compatibility: if parsed had primary_agent/sub_intents
                        if not actions and parsed.get("primary_agent"):
                            primary = parsed.get("primary_agent")
                            sub_intents = [
                                SubIntent(
                                    description=si.get("description", ""),
                                    target_agent=si.get("target_agent", ""),
                                    depends_on=si.get("depends_on", []),
                                )
                                for si in parsed.get("sub_intents", [])
                                if si.get("target_agent") in available_names
                            ]
                            return IntentClassification(
                                raw_intent=intent,
                                primary_agent=primary if primary in available_names else None,
                                confidence=float(parsed.get("confidence", 0.8)),
                                requires_multi_agent=bool(parsed.get("requires_multi_agent", False)),
                                sub_intents=sub_intents,
                                metadata={"strategy": "llm"},
                            )
                except Exception:
                    # Content is plain text response
                    direct_response = content

            # If no actions were produced by LLM, evaluate fallback
            if not actions:
                fallback_classification = await self._fallback.classify(
                    intent,
                    available_agents,
                    conversation_history=conversation_history,
                    **kwargs,
                )
                if fallback_classification.primary_agent is not None or fallback_classification.requires_multi_agent:
                    return fallback_classification

            # Validate generated actions before proceeding
            validated_actions: list[StructuredAction] = []
            for act in actions:
                if self._validator:
                    val = self._validator.validate(act)
                    if not val.is_valid:
                        logger.warning("Structured action validation failed: %s", val.error)
                        return IntentClassification(
                            raw_intent=intent,
                            primary_agent=act.agent_name,
                            confidence=0.0,
                            thought=f"Validation error: {val.error}",
                            direct_response=f"Action validation failed: {val.error}",
                            metadata={"strategy": "llm", "validation_error": val.error},
                        )
                    act.arguments = val.sanitized_arguments
                validated_actions.append(act)

            primary_agent = validated_actions[0].agent_name if validated_actions else None
            requires_multi = len(validated_actions) > 1

            return IntentClassification(
                raw_intent=intent,
                primary_agent=primary_agent,
                confidence=0.9 if validated_actions else (0.8 if direct_response else 0.0),
                requires_multi_agent=requires_multi,
                actions=validated_actions,
                thought=thought,
                direct_response=direct_response,
                metadata={"strategy": "llm"},
            )

        except Exception as exc:
            logger.warning(
                "LLM classification failed (%s), falling back to %s",
                exc,
                type(self._fallback).__name__,
            )
            return await self._fallback.classify(
                intent,
                available_agents,
                conversation_history=conversation_history,
                **kwargs,
            )

    def _find_owning_agent(self, tool_name: str, available_agents: list[AgentMeta]) -> str | None:
        """Find the agent that owns the given tool."""
        if self._registry:
            for agent in self._registry:
                if tool_name in agent.tools:
                    return agent.name
        tool_lower = tool_name.lower()
        if "file" in tool_lower:
            return "file_agent"
        if any(k in tool_lower for k in ("cpu", "memory", "disk", "os", "system", "process")):
            return "system_agent"
        if "app" in tool_lower:
            return "app_agent"
        return None
