"""Backward-compatibility shim — canonical location: lughus.governance.budget"""
import sys as _sys
from importlib import import_module as _import

_real = _import("lughus.governance.budget")
_sys.modules[__name__] = _real
