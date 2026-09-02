> [← Documentation index](../index.md)

# Agentic Design Rules

Eight rules that govern how lughus builds and manages the LLM conversation context. These rules are enforced by the framework internals and should guide agent authors when extending behavior.

## A1: Stable Prefix

The system prompt, context items, and tool declarations must be byte-identical across turns within a single `agent_loop` invocation. This enables provider-side prompt caching (OpenAI, Anthropic) to avoid re-processing the same prefix on every round-trip. Declarations are frozen and memoized at registration time to guarantee this.

## A2: Incremental History

Each loop iteration appends to the existing message list rather than rebuilding it from scratch. This preserves the cacheable prefix and avoids quadratic serialization costs. The only mutation allowed is pruning oldest atomic groups from the middle when the context budget is exceeded (see A4).

## A3: Conservative Token Estimation

Token counts used for context budget decisions are estimated conservatively -- they overcount rather than undercount. This ensures the context window is never silently exceeded, which would cause provider errors or silent truncation. The framework uses character-based heuristics rather than tokenizer calls to avoid a hard dependency on provider-specific tokenizers.

## A4: Atomic Tool Groups

An assistant message containing tool calls and its corresponding tool result messages form an atomic group that is never split. Removing a tool call without its result (or vice versa) produces an invalid conversation that most providers reject. When pruning for context budget, the framework removes entire groups or nothing.

## A5: Uniform Tool Result Contract

Every tool returns a JSON string. Success and failure both use a structured envelope so the LLM can parse results mechanically. Non-string return values are serialized automatically. This uniformity means the LLM never needs to guess the shape of a tool response.

## A6: Error Retryability

Tool failures are returned to the LLM as structured JSON with an `error_type` field rather than raising exceptions that abort the loop. This gives the LLM the opportunity to retry with corrected arguments or choose a different strategy. Only framework-level invariant violations (schema errors, budget exhaustion) raise exceptions.

## A7: Artifact Projection

Large tool outputs (files, images, long text) are stored in an artifact store and replaced with a short reference ID in the conversation. The LLM can retrieve content on demand via the built-in `fetch_artifact` tool. This prevents a single large output from consuming the entire context window.

## A8: Anti-Leak

Internal paths, stack traces, and framework internals are never included in model-facing output. Tool errors are redacted to structured error types without exposing server file paths or implementation details. This prevents prompt injection attacks from extracting infrastructure information through error messages.

---

**Related:** [Loop API](../api/loop.md) · [Tools Guide](tools.md) · [Context Contract](../contracts/context.md)
