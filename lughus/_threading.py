"""Backward-compatibility shim — canonical location: lughus.infra._threading"""
import sys as _sys
from importlib import import_module as _import

_real = _import("lughus.infra._threading")
_sys.modules[__name__] = _real
