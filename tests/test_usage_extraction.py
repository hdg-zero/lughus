"""Regression tests for token accounting (prompt/completion/cached)."""

from __future__ import annotations

from types import SimpleNamespace

from lughus.loop._execute import _extract_usage


class TestExtractUsage:
    def test_openai_style(self) -> None:
        usage = SimpleNamespace(prompt_tokens=100, completion_tokens=50)
        assert _extract_usage(usage) == (100, 50, 0)

    def test_openai_cached_details(self) -> None:
        usage = SimpleNamespace(
            prompt_tokens=100,
            completion_tokens=50,
            prompt_tokens_details=SimpleNamespace(cached_tokens=64),
        )
        assert _extract_usage(usage) == (100, 50, 64)

    def test_anthropic_aliases(self) -> None:
        """LiteLLM normalizes Anthropic to input_tokens/output_tokens."""
        usage = SimpleNamespace(input_tokens=80, output_tokens=40)
        prompt, completion, _cached = _extract_usage(usage)
        assert (prompt, completion) == (80, 40)

    def test_anthropic_cache_read(self) -> None:
        usage = SimpleNamespace(
            input_tokens=80,
            output_tokens=40,
            cache_read_input_tokens=32,
        )
        assert _extract_usage(usage) == (80, 40, 32)

    def test_gemini_aliases(self) -> None:
        usage = SimpleNamespace(
            prompt_token_count=200,
            candidates_token_count=60,
            cached_content_token_count=16,
        )
        prompt, completion, cached = _extract_usage(usage)
        assert (prompt, completion) == (200, 60)
        assert cached >= 16

    def test_dict_shape(self) -> None:
        usage = {"input_tokens": 10, "output_tokens": 5}
        assert _extract_usage(usage) == (10, 5, 0)

    def test_missing_fields_default_to_zero(self) -> None:
        assert _extract_usage(SimpleNamespace()) == (0, 0, 0)

    def test_none_values_default_to_zero(self) -> None:
        usage = SimpleNamespace(prompt_tokens=None, completion_tokens=None)
        assert _extract_usage(usage) == (0, 0, 0)


async def test_budgeted_llm_accounts_anthropic_and_gemini_tokens() -> None:
    from lughus.governance.budget import BudgetLedger, BudgetLimit
    from lughus.governance.budgeted_llm import BudgetedLLM

    class MockAnthropicLLM:
        model = "claude-3-7-sonnet"
        timeout = None

        async def generate(self, **kwargs: object) -> object:
            return SimpleNamespace(
                usage=SimpleNamespace(input_tokens=150, output_tokens=50),
            )

    ledger = BudgetLedger(BudgetLimit(model_calls=5, tokens=1000))
    b_llm = BudgetedLLM(MockAnthropicLLM(), ledger)
    await b_llm.generate(messages=[])
    snapshot = await ledger.snapshot()
    assert snapshot["model_calls"] == 1
    assert snapshot["tokens"] == 200

    class MockGeminiLLM:
        model = "gemini-2.5-flash"
        timeout = None

        async def generate(self, **kwargs: object) -> object:
            return SimpleNamespace(
                usage=SimpleNamespace(prompt_token_count=300, candidates_token_count=100),
            )

    b_gemini = BudgetedLLM(MockGeminiLLM(), ledger)
    await b_gemini.generate(messages=[])
    snapshot = await ledger.snapshot()
    assert snapshot["model_calls"] == 2
    assert snapshot["tokens"] == 600
