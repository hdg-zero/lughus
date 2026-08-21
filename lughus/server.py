"""Backward-compatibility shim — canonical location: lughus.interfaces.server"""
import sys as _sys
from importlib import import_module as _import

_real = _import("lughus.interfaces.server")
_sys.modules[__name__] = _real
