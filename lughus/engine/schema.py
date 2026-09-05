"""Automatic schema inference and docstring parsing for lughus tools."""

from __future__ import annotations

import inspect
import re
from collections.abc import Callable
from typing import Any, get_type_hints

from pydantic import BaseModel, Field, TypeAdapter, create_model

from ..core.errors import ToolValidationError

__all__ = [
    "infer_tool_schema",
    "parse_docstring",
    "resolve_output_schema",
]

_SPHINX_PARAM_RE = re.compile(r"^:param\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*:\s*(.*)$")
_GOOGLE_SECTION_RE = re.compile(
    r"^(Args|Arguments|Parameters|Returns|Return|Raises|Yields|Examples?):\s*$",
    re.IGNORECASE,
)
_GOOGLE_PARAM_RE = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_]*)(?:\s*\([^)]+\))?\s*:\s*(.*)$")


def parse_docstring(doc: str | None) -> tuple[str, dict[str, str]]:
    """Parse docstring into a main tool description and per-parameter descriptions.

    Supports both Google-style ('Args:') and Sphinx/reST-style (':param x:') formats.
    """
    if not doc:
        return "", {}

    lines = inspect.cleandoc(doc).splitlines()
    summary_lines: list[str] = []
    param_descriptions: dict[str, str] = {}

    in_summary = True
    in_google_args = False
    current_param: str | None = None
    current_param_lines: list[str] = []

    def _flush_current_param() -> None:
        nonlocal current_param, current_param_lines
        if current_param:
            param_descriptions[current_param] = " ".join(
                line.strip() for line in current_param_lines if line.strip()
            )
        current_param = None
        current_param_lines = []

    for line in lines:
        stripped = line.strip()

        # Check for Sphinx :param name: description
        sphinx_match = _SPHINX_PARAM_RE.match(stripped)
        if sphinx_match:
            in_summary = False
            _flush_current_param()
            p_name, p_desc = sphinx_match.group(1), sphinx_match.group(2).strip()
            current_param = p_name
            if p_desc:
                current_param_lines.append(p_desc)
            continue

        # Check for Google section header
        sec_match = _GOOGLE_SECTION_RE.match(stripped)
        if sec_match:
            in_summary = False
            _flush_current_param()
            section_name = sec_match.group(1).lower()
            in_google_args = section_name in {"args", "arguments", "parameters"}
            continue

        if in_google_args:
            # Check if this line introduces a parameter name: desc
            g_match = _GOOGLE_PARAM_RE.match(stripped)
            if g_match:
                _flush_current_param()
                p_name, p_desc = g_match.group(1), g_match.group(2).strip()
                current_param = p_name
                if p_desc:
                    current_param_lines.append(p_desc)
                continue
            if current_param and (line.startswith("    ") or line.startswith("\t")):
                # Continuation line of current parameter
                current_param_lines.append(stripped)
                continue

        if in_summary:
            if stripped.startswith(":") or _GOOGLE_SECTION_RE.match(stripped):
                in_summary = False
            else:
                summary_lines.append(line)

    _flush_current_param()
    main_desc = "\n".join(summary_lines).strip()
    return main_desc, param_descriptions


def infer_tool_schema(
    fn: Callable[..., Any],
    *,
    doc_params: dict[str, str] | None = None,
) -> tuple[dict[str, Any], bool]:
    """Infer OpenAI / Draft 2020-12 parameters JSON Schema from function signature.

    Returns:
        tuple[dict[str, Any], bool]: (parameters_schema, takes_state)
    """
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError) as exc:
        raise ToolValidationError(
            f"Tool '{getattr(fn, '__name__', str(fn))}' must have an inspectable signature"
        ) from exc

    try:
        type_hints = get_type_hints(fn)
    except Exception:  # noqa: BLE001
        type_hints = getattr(fn, "__annotations__", {})

    params = sig.parameters
    if any(p.kind is inspect.Parameter.POSITIONAL_ONLY for p in params.values()):
        fn_name = getattr(fn, "__name__", "tool")
        raise ToolValidationError(f"Tool '{fn_name}' must not use positional-only parameters")

    takes_state = "state" in params or any(
        p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()
    )

    doc_params = doc_params or {}
    fields: dict[str, Any] = {}

    for param_name, param in params.items():
        if param_name == "state":
            continue
        if param.kind in {
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        }:
            continue

        param_type = type_hints.get(param_name, str)
        has_default = param.default is not inspect.Parameter.empty
        default_val = param.default if has_default else ...
        desc = doc_params.get(param_name)

        if desc:
            field_info = Field(default=default_val, description=desc)
            fields[param_name] = (param_type, field_info)
        elif has_default:
            fields[param_name] = (param_type, default_val)
        else:
            fields[param_name] = (param_type, ...)

    fn_name = getattr(fn, "__name__", "tool")
    model = create_model(f"{fn_name}_parameters", **fields)
    schema = TypeAdapter(model).json_schema()

    # Remove top-level title generated by Pydantic
    schema.pop("title", None)
    if "type" not in schema:
        schema["type"] = "object"
    if "properties" not in schema:
        schema["properties"] = {}

    return schema, takes_state


def resolve_output_schema(
    fn: Callable[..., Any],
    explicit_schema: dict[str, Any] | type[BaseModel] | None = None,
) -> tuple[dict[str, Any] | None, type[BaseModel] | None]:
    """Resolve the JSON Schema and Pydantic model for tool return values."""
    if isinstance(explicit_schema, type) and issubclass(explicit_schema, BaseModel):
        schema = TypeAdapter(explicit_schema).json_schema()
        schema.pop("title", None)
        return schema, explicit_schema

    if isinstance(explicit_schema, dict):
        return explicit_schema, None

    if explicit_schema is None:
        try:
            hints = get_type_hints(fn)
        except Exception:  # noqa: BLE001
            hints = getattr(fn, "__annotations__", {})

        ret_type = hints.get("return")
        if isinstance(ret_type, type) and issubclass(ret_type, BaseModel):
            schema = TypeAdapter(ret_type).json_schema()
            schema.pop("title", None)
            return schema, ret_type

    return None, None
