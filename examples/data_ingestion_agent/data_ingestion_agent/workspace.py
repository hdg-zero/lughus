"""Workspace orchestration for the Data Ingestion Agent."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from lughus import (
    BudgetAmount,
    BudgetLedger,
    BudgetLimit,
    CompletionEvent,
    ProgressEvent,
    ToolExecutionConfig,
    agent_loop,
)

from .tools import TOOL_NAMES, registry

SYSTEM_PROMPT = """\
You are an expert Data Ingestion & SQL Specialist Agent built with Lughus.

Your role is to inspect the on-premise relational database, understand schema
relationships, profile table contents, and execute targeted read-only SQL
queries to extract data needed for analysis.

Database Schema Overview:
- `warehouses`: facilities (`warehouse_code`, `city`, `country`,
  `capacity_utilization_pct`, `is_automated`)
- `customers`: client accounts (`customer_id`, `company_name`, `tier`, `region`)
  tier values: 'Enterprise', 'Mid-Market', 'SMB'
- `orders`: purchase orders (`order_id`, `customer_id`, `warehouse_code`,
  `order_date`, `amount_eur`, `priority`)
  priority values: 'Critical', 'Express', 'Standard'
- `fulfillment_delays`: delivery performance (`order_id`, `promised_date`,
  `actual_delivery_date`, `delay_days`, `delay_category`)
  delay_category values: 'Warehouse Overload', 'Carrier Strike',
  'Customs Inspection', 'Weather', 'None'

Guidelines:
1. Formulate concise, efficient read-only `SELECT` queries with `query_database`
   to aggregate, filter, and extract metrics.
2. Only `SELECT` and `WITH` statements are permitted in `query_database`. Do NOT
   run `PRAGMA` or metadata statements; use `describe_table` or `list_tables`
   if you need schema details.
3. Map user terminology to the actual schema (e.g. priorities 'HIGH' / 'URGENT'
   map to 'Critical' / 'Express'; carrier incidents map to 'Carrier Strike').
4. As soon as you obtain the query results, synthesize your final answer
   clearly with the extracted figures and metrics without redundant tool calls.
"""


class Workspace:
    """Orchestrates an ingestion and SQL inspection workflow for a single run."""

    def __init__(
        self,
        objective: str,
        llm: Any,
        tool_config: ToolExecutionConfig,
        files: list[Any] | None = None,
        budget_limit: BudgetLimit | None = None,
        max_iterations: int = 15,
    ) -> None:
        self.objective = objective
        self.files = files or []
        self.llm = llm
        self.tool_config = tool_config
        self.max_iterations = max_iterations
        self.budget_limit = budget_limit or BudgetLimit(
            model_calls=20,
            tool_calls=35,
            tokens=100_000,
            delegation_depth=0,
        )

    async def run(self) -> AsyncIterator[ProgressEvent | CompletionEvent]:
        """Execute the ingestion loop with governance and streaming progress."""
        yield ProgressEvent("Starting data ingestion and SQL inspection session...")

        ledger = BudgetLedger(self.budget_limit)
        reservation = await ledger.reserve(
            BudgetAmount(
                model_calls=self.max_iterations,
                tool_calls=self.max_iterations * 2,
                tokens=self.budget_limit.tokens,
            )
        )

        # Append any textual files/schemas attached to the request
        context_parts = [self.objective]
        for file_item in self.files:
            if hasattr(file_item, "data") and hasattr(file_item, "name"):
                try:
                    text_content = file_item.data.decode("utf-8")
                    snippet = text_content[:15000]
                    context_parts.append(f"\n--- Attached File: {file_item.name} ---\n{snippet}")
                except (UnicodeDecodeError, AttributeError):
                    pass

        context = "\n\n".join(context_parts)

        try:
            result = await agent_loop(
                self.llm,
                system=SYSTEM_PROMPT,
                context=context,
                registry=registry,
                tool_names=TOOL_NAMES,
                tool_config=self.tool_config,
                max_iterations=self.max_iterations,
            )

            # Settle actual consumed budget
            await ledger.settle(
                reservation,
                BudgetAmount(
                    model_calls=result.iterations,
                    tool_calls=max(result.iterations - 1, 0),
                    tokens=result.total_tokens,
                ),
            )

            yield CompletionEvent(
                text=str(result),
                metadata={
                    "iterations": result.iterations,
                    "elapsed_s": round(result.elapsed, 3),
                    "total_tokens": result.total_tokens,
                    "cached_tokens": result.cached_tokens,
                },
            )
        except Exception:
            await ledger.release(reservation)
            raise
