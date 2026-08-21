"""Backward-compatibility shim — canonical location: lughus.persistence.resume"""
import sys as _sys
from importlib import import_module as _import

_real = _import("lughus.persistence.resume")
_sys.modules[__name__] = _real
