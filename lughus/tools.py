"""Per-instance tool registry — OpenAI function-calling format (LiteLLM-compatible)."""
from __future__ import annotations

import logging
import inspect
import copy
from dataclasses import dataclass
from typing import Any, Callable

from jsonschema import Draft202012Validator, SchemaError  # type: ignore[import-untyped]

from .errors import ToolValidationError

_logger = logging.getLogger(__name__)


def _compact_schema(schema: Any) -> Any:
    """Return a schema copy without descriptive prose.

    Provider-side tool declarations are sent on every tool-capable LLM call.
    JSON Schema metadata like ``description`` is helpful while developing but
    can dominate prompt tokens for agents with many tools.
    """
    if isinstance(schema, dict):
        return {
            key: _compact_schema(value)
            for key, value in schema.items()
            if key != "description"
        }
    if isinstance(schema, list):
        return [_compact_schema(item) for item in schema]
    return copy.deepcopy(schema)


def _validate_tool_callable(name: str, fn: Callable[..., Any], parameters_schema: dict) -> None:
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError) as exc:
        raise ToolValidationError(
            f"Tool '{name}' must have an inspectable signature"
        ) from exc

    params = signature.parameters
    if any(p.kind is inspect.Parameter.POSITIONAL_ONLY for p in params.values()):
        raise ToolValidationError(
            f"Tool '{name}' must not use positional-only parameters"
        )

    has_var_keyword = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())
    properties = parameters_schema.get("properties", {})
    if isinstance(properties, dict) and not has_var_keyword:
        keyword_params = {
            param_name
            for param_name, parameter in params.items()
            if param_name != "state"
            and parameter.kind in {
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
            raise ToolValidationError(
                f"Tool '{name}' parameter 'state' must be keyword-callable"
            )
        return
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return
    raise ToolValidationError(
        f"Tool '{name}' must accept a keyword-only or **kwargs 'state' parameter"
    )


@dataclass
class ToolDef:
    """A tool definition: name, description, callable, and JSON Schema."""
    name: str
    description: str
    fn: Callable[..., Any]
    parameters_schema: dict
    validator: Draft202012Validator


class ToolRegistry:
    """Per-instance tool registry — each agent creates its own."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDef] = {}

    def tool(
        self, name: str, description: str, parameters: dict,
    ) -> Callable:
        """Decorator to register a tool function (sync or async)."""
        if name in self._tools:
            raise ToolValidationError(f"Tool '{name}' is already registered")
        try:
            Draft202012Validator.check_schema(parameters)
            validator = Draft202012Validator(parameters)
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
            )
            return fn
        return decorator

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
        compact: bool = False,
    ) -> list[dict]:
        """Return OpenAI-format tool declarations for the given tool names.

        Unknown names are skipped with a WARNING log. The returned list
        preserves the order of ``names``. When ``compact`` is true, parameter
        schema descriptions are stripped to reduce repeated prompt tokens.
        """
        result = []
        for n in names:
            td = self._tools.get(n)
            if td is None:
                if strict:
                    raise ToolValidationError(f"Tool '{n}' is not registered")
                _logger.warning("Tool '%s' not found in registry — skipped", n)
                continue
            result.append({
                "type": "function",
                "function": {
                    "name": td.name,
                    "description": td.description,
                    "parameters": (
                        _compact_schema(td.parameters_schema)
                        if compact
                        else copy.deepcopy(td.parameters_schema)
                    ),
                },
            })
        return result
