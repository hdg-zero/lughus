"""Backward-compatibility shim — canonical location: lughus.governance.budgeted_llm"""
import sys as _sys
from importlib import import_module as _import

_real = _import("lughus.governance.budgeted_llm")
_sys.modules[__name__] = _real
