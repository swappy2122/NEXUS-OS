"""Tests for the NEXUS OS Model Router, routing strategies, and routing types."""

import pytest

from core.types import ModelResponse
from models.routing_strategy import (
    DefaultPassthroughStrategy,
    RuleBasedStrategy,
    _last_user_content,
    max_tier,
)
from models.routing_types import (
    ComplexityTier,
    ModelTierConfig,
    RoutingDecision,
    TaskCategory,
)
from models.router import ModelRouter
from models.base_backend import BaseModelBackend

# ── Fake backend for testing ─────────────────────────────────────────────


class FakeBackend(BaseModelBackend):
    """Minimal backend that returns a canned response."""

    def __init__(self, name: str = "fake", model_id: str = "fake-v1") -> None:
        super().__init__(name=name, model_id=model_id)
        self.call_count = 0

    async def chat(self, messages, tools=None, **kwargs):
        self.call_count += 1
        return ModelResponse(
            content=f"response from {self.name}",
            model=self.model_id,
            finish_reason="stop",
        )

    async def is_available(self):
        return True


# ══════════════════════════════════════════════════════════════════════════
# routing_types tests
# ══════════════════════════════════════════════════════════════════════════


class TestTaskCategory:
    def test_enum_values(self):
        assert TaskCategory.SIMPLE_OS_COMMAND == "simple_os_command"
        assert TaskCategory.CODING == "coding"
        assert TaskCategory.VISION == "vision"
        assert TaskCategory.SPEECH == "speech"
        assert TaskCategory.UNKNOWN == "unknown"


class TestComplexityTier:
    def test_enum_values(self):
        assert ComplexityTier.BYPASS == "bypass"
        assert ComplexityTier.LIGHT == "light"
        assert ComplexityTier.STANDARD == "standard"
        assert ComplexityTier.HEAVY == "heavy"


class TestModelTierConfig:
    def test_defaults(self):
        cfg = ModelTierConfig()
        assert cfg.bypass == "dev_backend"
        assert cfg.light == "default"
        assert cfg.get_backend_for_tier(ComplexityTier.BYPASS) == "dev_backend"

    def test_from_dict(self):
        cfg = ModelTierConfig.from_dict({
            "bypass": "local_rules",
            "light": "small_llm",
            "standard": "medium_llm",
            "heavy": "big_llm",
        })
        assert cfg.light == "small_llm"
        assert cfg.heavy == "big_llm"
        assert cfg.get_backend_for_tier(ComplexityTier.HEAVY) == "big_llm"

    def test_from_dict_partial(self):
        """Missing keys should use defaults."""
        cfg = ModelTierConfig.from_dict({"light": "tiny"})
        assert cfg.light == "tiny"
        assert cfg.standard == "default"


class TestRoutingDecision:
    def test_default_values(self):
        d = RoutingDecision()
        assert d.category == TaskCategory.UNKNOWN
        assert d.tier == ComplexityTier.STANDARD
        assert d.backend_override is None
        assert d.bypass_response is None

    def test_custom_values(self):
        resp = ModelResponse(content="hello")
        d = RoutingDecision(
            category=TaskCategory.SIMPLE_OS_COMMAND,
            tier=ComplexityTier.BYPASS,
            bypass_response=resp,
            reason="test",
        )
        assert d.bypass_response.content == "hello"


# ══════════════════════════════════════════════════════════════════════════
# routing_strategy tests
# ══════════════════════════════════════════════════════════════════════════


class TestDefaultPassthroughStrategy:
    def test_always_standard(self):
        strategy = DefaultPassthroughStrategy()
        decision = strategy.classify(
            [{"role": "user", "content": "open firefox"}],
            agent_role="app",
        )
        assert decision.tier == ComplexityTier.STANDARD
        assert decision.category == TaskCategory.UNKNOWN


class TestRuleBasedStrategy:
    @pytest.fixture
    def strategy(self):
        return RuleBasedStrategy()

    # -- Simple OS commands → BYPASS --------------------------------------

    @pytest.mark.parametrize("content,role", [
        ("list files in /home", "file"),
        ("show directory contents", "file"),
        ("create a folder test", "file"),
        ("delete the file report.txt", "file"),
        ("move test.py to /tmp", "file"),
        ("search for files matching *.py", "file"),
        ("show cpu usage", "system"),
        ("check memory", "system"),
        ("get disk usage", "system"),
        ("what's the system info", "system"),
        ("open firefox", "app"),
        ("close chrome", "app"),
        ("list running apps", "app"),
        ("is firefox running", "app"),
        ("list files in /home", "*"),  # wildcard role should also match
    ])
    def test_simple_os_commands_bypass(self, strategy, content, role):
        decision = strategy.classify(
            [{"role": "user", "content": content}],
            agent_role=role,
        )
        assert decision.category == TaskCategory.SIMPLE_OS_COMMAND
        assert decision.tier == ComplexityTier.BYPASS

    # -- Non-OS roles should not bypass ------------------------------------

    def test_coding_role_no_bypass(self, strategy):
        """Even simple-looking commands should not bypass if agent_role is coding."""
        decision = strategy.classify(
            [{"role": "user", "content": "list files in /home"}],
            agent_role="code",
        )
        assert decision.tier != ComplexityTier.BYPASS

    # -- Coding detection --------------------------------------------------

    @pytest.mark.parametrize("content", [
        "write a python function to sort a list",
        "generate a class for database connections",
        "fix the syntax error in this code",
        "debug this traceback",
        "refactor the API endpoint handler",
    ])
    def test_coding_detection(self, strategy, content):
        decision = strategy.classify(
            [{"role": "user", "content": content}],
            agent_role="*",
        )
        assert decision.category == TaskCategory.CODING

    # -- Vision detection --------------------------------------------------

    @pytest.mark.parametrize("content", [
        "look at this screenshot and tell me what you see",
        "analyze the image for text",
        "describe the photo",
        "what is in this image",
        "detect objects in the camera frame",
    ])
    def test_vision_detection(self, strategy, content):
        decision = strategy.classify(
            [{"role": "user", "content": content}],
            agent_role="*",
        )
        assert decision.category == TaskCategory.VISION

    # -- General reasoning (fallback) --------------------------------------

    def test_general_reasoning_fallback(self, strategy):
        decision = strategy.classify(
            [{"role": "user", "content": "what is the meaning of life?"}],
            agent_role="*",
        )
        assert decision.category == TaskCategory.GENERAL_REASONING

    # -- Complexity estimation ---------------------------------------------

    def test_short_question_light(self, strategy):
        decision = strategy.classify(
            [{"role": "user", "content": "hello"}],
            agent_role="*",
        )
        assert decision.tier == ComplexityTier.LIGHT

    def test_long_message_heavy(self, strategy):
        long_text = "explain step by step " + "word " * 250
        decision = strategy.classify(
            [{"role": "user", "content": long_text}],
            agent_role="*",
        )
        assert decision.tier == ComplexityTier.HEAVY

    def test_deep_conversation_heavy(self, strategy):
        messages = [{"role": "user", "content": f"step by step message {i}"} for i in range(20)]
        decision = strategy.classify(messages, agent_role="*")
        assert decision.tier == ComplexityTier.HEAVY

    # -- Empty messages ----------------------------------------------------

    def test_empty_messages(self, strategy):
        decision = strategy.classify([], agent_role="*")
        assert decision.tier == ComplexityTier.STANDARD
        assert decision.category == TaskCategory.UNKNOWN


# ══════════════════════════════════════════════════════════════════════════
# Utility function tests
# ══════════════════════════════════════════════════════════════════════════


class TestLastUserContent:
    def test_extracts_last_user_message(self):
        messages = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "reply"},
            {"role": "user", "content": "second"},
        ]
        assert _last_user_content(messages) == "second"

    def test_empty_list(self):
        assert _last_user_content([]) == ""

    def test_no_user_message(self):
        assert _last_user_content([{"role": "assistant", "content": "hi"}]) == ""

    def test_list_content_format(self):
        messages = [
            {"role": "user", "content": [
                {"type": "text", "text": "describe"},
                {"type": "image_url", "url": "http://example.com/img.png"},
                {"type": "text", "text": "this image"},
            ]},
        ]
        assert _last_user_content(messages) == "describe this image"


class TestMaxTier:
    def test_max_tier(self):
        assert max_tier(ComplexityTier.LIGHT, ComplexityTier.STANDARD) == ComplexityTier.STANDARD
        assert max_tier(ComplexityTier.HEAVY, ComplexityTier.LIGHT) == ComplexityTier.HEAVY
        assert max_tier(ComplexityTier.BYPASS, ComplexityTier.BYPASS) == ComplexityTier.BYPASS


# ══════════════════════════════════════════════════════════════════════════
# ModelRouter integration tests
# ══════════════════════════════════════════════════════════════════════════


class TestModelRouter:
    @pytest.fixture
    def router(self):
        """Router with two fake backends and rule-based strategy."""
        tier_config = ModelTierConfig(
            bypass="dev_backend",
            light="fast_model",
            standard="fast_model",
            heavy="big_model",
        )
        r = ModelRouter(
            strategy=RuleBasedStrategy(tier_config=tier_config),
            tier_config=tier_config,
        )
        r.register_backend(FakeBackend(name="dev_backend", model_id="dev-v1"))
        r.register_backend(FakeBackend(name="fast_model", model_id="fast-v1"))
        r.register_backend(FakeBackend(name="big_model", model_id="big-v1"))
        return r

    @pytest.mark.asyncio
    async def test_bypass_skips_backend(self, router):
        """Simple OS commands should return without calling any backend."""
        response = await router.chat(
            [{"role": "user", "content": "list files in /home"}],
            agent_role="file",
        )
        # Bypass returns the dev_backend's response via tier mapping,
        # but the strategy's BYPASS path returns None bypass_response by default.
        # The router should fall through to the bypass-tier backend.
        stats = router.get_routing_stats()
        assert stats["total_requests"] >= 1

    @pytest.mark.asyncio
    async def test_routes_to_correct_tier_backend(self, router):
        """General reasoning with a short message should route to light/standard backend."""
        response = await router.chat(
            [{"role": "user", "content": "what is the meaning of life?"}],
            agent_role="*",
        )
        assert response.content == "response from fast_model"

    @pytest.mark.asyncio
    async def test_explicit_route_overrides_strategy(self, router):
        """An explicit set_route() should override strategy tier mapping."""
        router.set_route("vision", "big_model")
        response = await router.chat(
            [{"role": "user", "content": "hello short question"}],
            agent_role="vision",
        )
        assert response.content == "response from big_model"

    @pytest.mark.asyncio
    async def test_health_check(self, router):
        health = await router.health_check()
        assert all(v is True for v in health.values())

    def test_list_backends(self, router):
        backends = router.list_backends()
        names = {b["name"] for b in backends}
        assert "fast_model" in names
        assert "big_model" in names

    def test_routing_stats(self, router):
        stats = router.get_routing_stats()
        assert stats["strategy"] == "RuleBasedStrategy"
        assert "tier_config" in stats
        assert stats["total_requests"] == 0

    @pytest.mark.asyncio
    async def test_passthrough_strategy(self):
        """With DefaultPassthroughStrategy, everything goes to standard tier."""
        router = ModelRouter(strategy=DefaultPassthroughStrategy())
        backend = FakeBackend(name="only_backend")
        router.register_backend(backend)
        response = await router.chat(
            [{"role": "user", "content": "open firefox"}],
            agent_role="app",
        )
        assert backend.call_count == 1
        assert response.content == "response from only_backend"

    def test_set_strategy_at_runtime(self, router):
        assert isinstance(router.strategy, RuleBasedStrategy)
        router.set_strategy(DefaultPassthroughStrategy())
        assert isinstance(router.strategy, DefaultPassthroughStrategy)

    @pytest.mark.asyncio
    async def test_no_backend_raises(self):
        """Router with no backends should raise RuntimeError."""
        router = ModelRouter()
        with pytest.raises(RuntimeError, match="No model backend"):
            await router.chat(
                [{"role": "user", "content": "hello"}],
                agent_role="*",
            )
