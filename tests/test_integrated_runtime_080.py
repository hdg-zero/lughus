import pytest

from lughus.governance.budget import BudgetLedger, BudgetLimit
from lughus.governance.budgeted_llm import BudgetedLLM
from lughus.core.context import ContextItem, ContextManager, TrustLevel


class _Usage:
    prompt_tokens = 3
    completion_tokens = 2


class _Response:
    usage = _Usage()


class _LLM:
    model = "test"
    timeout = None

    async def generate(self, **kwargs):
        return _Response()


@pytest.mark.asyncio
async def test_budgeted_llm_accounts_for_calls_and_tokens():
    ledger = BudgetLedger(BudgetLimit(model_calls=2, tokens=10))
    await BudgetedLLM(_LLM(), ledger).generate(messages=[])
    snapshot = await ledger.snapshot()
    assert snapshot["model_calls"] == 1 and snapshot["tokens"] == 5


def test_context_selection_preserves_provenance():
    window = ContextManager(20).select(
        [
            ContextItem("system", "rules", "app", TrustLevel.SYSTEM),
            ContextItem("user", "question", "user", TrustLevel.USER),
        ]
    )
    assert window.messages()[0]["role"] == "system"
