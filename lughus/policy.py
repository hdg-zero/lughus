"""Backward-compatibility shim — canonical location: lughus.governance.policy"""
import sys as _sys
from importlib import import_module as _import

_real = _import("lughus.governance.policy")
_sys.modules[__name__] = _real
