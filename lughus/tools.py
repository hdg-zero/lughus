"""Per-instance tool registry — OpenAI function-calling format (LiteLLM-compatible)."""

from __future__ import annotations

import copy
import inspect
import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from jsonschema import Draft202012Validator, SchemaError  # type: ignore[import-untyped]

from .errors import ToolValidationError

__all__ = [
    "ConcurrencyMode",
    "ToolDef",
    "ToolEffect",
    "ToolRegistry",
    "ToolRisk",
]

_logger = logging.getLogger(__name__)


class _FrozenDict(dict):
    """A ``dict`` subclass that raises on any mutation attempt.

    Inherits from ``dict`` so that ``isinstance(x, dict)`` checks in
    LLM SDKs (LiteLLM, OpenAI) remain satisfied, while structurally
    preventing accidental mutations that would break byte-identity of
    cached tool declarations.
    """

    __slots__ = ()

    def __setitem__(self, key: Any, value: Any) -> None:
        raise TypeError("FrozenDict does not support item assignment")

    def __delitem__(self, key: Any) -> None:
        raise TypeError("FrozenDict does not support item deletion")

    def update(self, *args: Any, **kwargs: Any) -> None:  # type: ignore[override]
        raise TypeError("FrozenDict does not support update")

    def pop(self, *args: Any) -> Any:
        raise TypeError("FrozenDict does not support pop")

    def popitem(self) -> tuple:
        raise TypeError("FrozenDict does not support popitem")  # type: ignore[return-value]

    def clear(self) -> None:
        raise TypeError("FrozenDict does not support clear")

    def setdefault(self, key: Any, default: Any = None) -> Any:
        raise TypeError("FrozenDict does not support setdefault")

    def __ior__(self, other: Any) -> Any:
        raise TypeError("FrozenDict does not support |= operator")

    def __copy__(self) -> dict:
        return dict(self)

    def __deepcopy__(self, memo: Any) -> dict:
        import copy as _copy

        return {_copy.deepcopy(k, memo): _copy.deepcopy(v, memo) for k, v in self.items()}


def _deep_freeze(obj: Any) -> Any:
    """Recursively freeze a JSON-like structure.

    ``dict`` -> :class:`_FrozenDict`, ``list`` -> ``tuple``,
    primitives pass through unchanged (already immutable).
    """
    if isinstance(obj, dict):
        return _FrozenDict({k: _deep_freeze(v) for k, v in obj.items()})
    if isinstance(obj, (list, tuple)):
        return tuple(_deep_freeze(item) for item in obj)
    return obj


def _compact_schema(schema: Any) -> Any:
    """Return a schema copy without descriptive prose.

    Provider-side tool declarations are sent on every tool-capable LLM call.
    JSON Schema metadata like ``description`` is helpful while developing but
    can dominate prompt tokens for agents with many tools.
    """
    if isinstance(schema, dict):
        return {
            key: _compact_schema(value) for key, value in schema.items() if key != "description"
        }
    if isinstance(schema, list):
        return [_compact_schema(item) for item in schema]
    return schema  # primitives (str, int, bool, None) are already immutable


def _validate_tool_callable(name: str, fn: Callable[..., Any], parameters_schema: dict) -> None:
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError) as exc:
        raise ToolValidationError(f"Tool '{name}' must have an inspectable signature") from exc

    params = signature.parameters
    if any(p.kind is inspect.Parameter.POSITIONAL_ONLY for p in params.values()):
        raise ToolValidationError(f"Tool '{name}' must not use positional-only parameters")

    has_var_keyword = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())
    properties = parameters_schema.get("properties", {})
    if isinstance(properties, dict) and not has_var_keyword:
        keyword_params = {
            param_name
            for param_name, parameter in params.items()
            if param_name != "state"
            and parameter.kind
            in {
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.KEYWORD_ONLY,
            }
        }
        unknown_schema_params = sorted(set(properties) - keyword_params)
        if unknown_schema_params:
            joined = ", ".join(unknown_schema_params)
            raise ToolValidationError(
                f"Tool '{name}' schema defines parameters not accepted by the callable: {joined}"
            )

    if "state" in params:
        parameter = params["state"]
        if parameter.kind in {
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.VAR_POSITIONAL,
        }:
            raise ToolValidationError(f"Tool '{name}' parameter 'state' must be keyword-callable")
        return
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return
    raise ToolValidationError(
        f"Tool '{name}' must accept a keyword-only or **kwargs 'state' parameter"
    )


class ToolEffect(StrEnum):
    READ = "read"
    WRITE = "write"
    EXTERNAL = "external"
    IRREVERSIBLE = "irreversible"


class ToolRisk(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class ConcurrencyMode(StrEnum):
    PARALLEL_SAFE = "parallel_safe"
    SERIAL_PER_TOOL = "serial_per_tool"
    SERIAL_PER_RESOURCE = "serial_per_resource"
    GLOBAL_EXCLUSIVE = "global_exclusive"


@dataclass(frozen=True)
class ToolDef:
    """A tool definition: name, description, callable, and JSON Schema."""

    name: str
    description: str
    fn: Callable[..., Any]
    parameters_schema: dict
    validator: Draft202012Validator
    output_schema: dict | None = None
    output_validator: Draft202012Validator | None = None
    version: str = "1"
    effects: frozenset[ToolEffect] = field(default_factory=frozenset)
    risk: ToolRisk = ToolRisk.UNKNOWN
    required_scopes: frozenset[str] = field(default_factory=frozenset)
    idempotent: bool = False
    requires_approval: bool = False
    concurrency: ConcurrencyMode = ConcurrencyMode.PARALLEL_SAFE
    resource_key: Callable[[Mapping[str, Any]], str] | None = None


class ToolRegistry:
    """Per-instance tool registry — each agent creates its own."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDef] = {}
        self._declarations_cache: dict[
            tuple[tuple[str, ...], bool], tuple[tuple[dict, ...], str]
        ] = {}

    def tool(
        self,
        name: str,
        description: str,
        parameters: dict,
        *,
        output_schema: dict | None = None,
        version: str = "1",
        effects: frozenset[ToolEffect] | None = None,
        risk: ToolRisk = ToolRisk.UNKNOWN,
        required_scopes: frozenset[str] | None = None,
        idempotent: bool = False,
        requires_approval: bool = False,
        concurrency: ConcurrencyMode = ConcurrencyMode.PARALLEL_SAFE,
        resource_key: Callable[[Mapping[str, Any]], str] | None = None,
    ) -> Callable:
        """Decorator to register a tool function (sync or async)."""
        if name in self._tools:
            raise ToolValidationError(f"Tool '{name}' is already registered")
        if concurrency == ConcurrencyMode.SERIAL_PER_RESOURCE and resource_key is None:
            raise ToolValidationError(
                f"Tool '{name}' uses SERIAL_PER_RESOURCE but no resource_key was provided"
            )
        try:
            Draft202012Validator.check_schema(parameters)
            validator = Draft202012Validator(parameters)
            if output_schema is not None:
                Draft202012Validator.check_schema(output_schema)
            output_validator = Draft202012Validator(output_schema) if output_schema else None
        except SchemaError as exc:
            raise ToolValidationError(f"Invalid schema for tool '{name}': {exc.message}") from exc

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            _validate_tool_callable(name, fn, parameters)
            self._tools[name] = ToolDef(
                name=name,
                description=description,
                fn=fn,
                parameters_schema=parameters,
                validator=validator,
                output_schema=copy.deepcopy(output_schema),
                output_validator=output_validator,
                version=version,
                effects=effects or frozenset(),
                risk=risk,
                required_scopes=required_scopes or frozenset(),
                idempotent=idempotent,
                requires_approval=requires_approval,
                concurrency=concurrency,
                resource_key=resource_key,
            )
            self._declarations_cache.clear()
            return fn

        return decorator

    def names(self) -> tuple[str, ...]:
        """Return the registered tool names, in registration order.

        Deliberately NOT added: describe(), filter_by_risk(), groups(), iteration
        over ToolDef. No demonstrated need today.
        """
        return tuple(self._tools)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._tools

    def __len__(self) -> int:
        return len(self._tools)

    def get_fn(self, name: str) -> Callable[..., str] | None:
        """Return the callable for a tool, or None if not found."""
        td = self._tools.get(name)
        return td.fn if td else None

    def get_tool(self, name: str) -> ToolDef | None:
        """Return the full tool definition, or None if not found."""
        return self._tools.get(name)

    def declarations(
        self,
        names: list[str],
        *,
        strict: bool = False,
    ) -> tuple[dict, ...]:
        """Return frozen OpenAI-format tool declarations for the given tool names.

        The result is memoized and structurally immutable (``tuple`` of
        :class:`_FrozenDict`).  Because mutation is impossible, no
        ``deepcopy`` is needed in the hot loop -- the same object can be
        reused across turns, preserving byte-identical prefix caching.

        Unknown names are skipped with a WARNING log (or raise when
        *strict* is ``True``).  The returned tuple preserves the order of
        ``names``.  Parameter schema descriptions are always stripped to
        reduce repeated prompt tokens.
        """
        cache_key = (tuple(names), strict)
        cached = self._declarations_cache.get(cache_key)
        if cached is not None:
            return cached[0]

        result: list[dict] = []
        for n in names:
            td = self._tools.get(n)
            if td is None:
                if strict:
                    raise ToolValidationError(f"Tool '{n}' is not registered")
                _logger.warning("Tool '%s' not found in registry — skipped", n)
                continue
            result.append(
                {
                    "type": "function",
                    "function": {
                        "name": td.name,
                        "description": td.description,
                        "parameters": _compact_schema(td.parameters_schema),
                    },
                }
            )

        frozen = _deep_freeze(result)
        canonical = json.dumps(
            result, sort_keys=True, separators=(",", ":"),
        )
        self._declarations_cache[cache_key] = (frozen, canonical)
        return frozen

    def declarations_json(
        self,
        names: list[str],
        *,
        strict: bool = False,
    ) -> str:
        """Return the canonical JSON serialization of tool declarations.

        Sorted keys, compact separators ``(",",":")``.  The returned
        string is byte-identical across calls with the same *names*,
        which is the foundation for provider-side prefix caching.
        """
        cache_key = (tuple(names), strict)
        cached = self._declarations_cache.get(cache_key)
        if cached is not None:
            return cached[1]
        # Populate the cache via declarations() and then retrieve.
        self.declarations(names, strict=strict)
        return self._declarations_cache[cache_key][1]
