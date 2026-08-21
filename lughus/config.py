"""Backward-compatibility shim — canonical location: lughus.infra.config"""
import sys as _sys
from importlib import import_module as _import

_real = _import("lughus.infra.config")
_sys.modules[__name__] = _real
