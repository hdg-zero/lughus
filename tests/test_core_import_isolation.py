"""the core must import with base dependencies only.

Regression guard for the defect that made `pip install lughus` unusable: the
package eagerly imported `opentelemetry.sdk` (via telemetry.py), `a2a` (via
gateway.py) and starlette/uvicorn (via server.py), all of which live in optional
extras.

The optional modules are blocked with a `sys.meta_path` finder in a subprocess
rather than by relying on a bare environment. That matters: CI installs
`--all-extras`, so a test that merely imports lughus would pass here and still
let the regression through. Blocking makes the test valid *in the development
environment*, which is where it has to be able to fail.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

BLOCKER = textwrap.dedent(
    """
    import sys

    BLOCKED = (
        "a2a",
        "starlette",
        "fastapi",
        "uvicorn",
        "sse_starlette",
        "opentelemetry.sdk",
        "opentelemetry.exporter",
    )


    class _Blocker:
        \"\"\"Meta path finder that makes the optional extras look uninstalled.\"\"\"

        def find_spec(self, name, path=None, target=None):
            if name.startswith(BLOCKED):
                raise ModuleNotFoundError(f"blocked by test: {name}", name=name)
            return None


    sys.meta_path.insert(0, _Blocker())
    """
)


def _run(body: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", BLOCKER + textwrap.dedent(body)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_core_imports_without_optional_extras() -> None:
    result = _run(
        """
        import lughus

        # A representative slice of the core surface, one symbol per subsystem.
        for name in (
            "agent_loop",
            "agent_loop_stream",
            "ToolRegistry",
            "ToolExecutionConfig",
            "BudgetLedger",
            "InMemoryIdempotencyStore",
            "InMemoryApprovalStore",
            "GovernedAgentRunner",
            "ExecutionRuntime",
            "LLM",
        ):
            assert getattr(lughus, name) is not None, name
        print("core-ok")
        """
    )
    assert result.returncode == 0, result.stderr
    assert "core-ok" in result.stdout


def test_optional_surface_names_the_missing_extra() -> None:
    """An unavailable symbol must say which extra to install, not raise ModuleNotFoundError."""
    result = _run(
        """
        import lughus

        for name in ("BaseGateway", "build_app", "serve", "BoundedInMemoryTaskStore"):
            try:
                getattr(lughus, name)
            except ImportError as exc:
                assert "lughus[server]" in str(exc), (name, str(exc))
            else:
                raise AssertionError(f"lughus.{name} should have raised ImportError")
        print("extras-ok")
        """
    )
    assert result.returncode == 0, result.stderr
    assert "extras-ok" in result.stdout


def test_setup_telemetry_names_the_missing_extra() -> None:
    result = _run(
        """
        import lughus

        try:
            lughus.setup_telemetry("svc")
        except ImportError as exc:
            assert "lughus[otel]" in str(exc), str(exc)
        else:
            raise AssertionError("setup_telemetry() should have raised ImportError")
        print("otel-ok")
        """
    )
    assert result.returncode == 0, result.stderr
    assert "otel-ok" in result.stdout


def test_unknown_attribute_still_raises_attribute_error() -> None:
    """The lazy __getattr__ must not turn typos into ImportError."""
    result = _run(
        """
        import lughus

        try:
            lughus.NoSuchSymbol
        except AttributeError as exc:
            assert "NoSuchSymbol" in str(exc)
        else:
            raise AssertionError("expected AttributeError")
        print("attr-ok")
        """
    )
    assert result.returncode == 0, result.stderr
    assert "attr-ok" in result.stdout


def test_lazy_access_is_memoised() -> None:
    """Second access must not re-enter __getattr__ (it is cached in globals())."""
    import lughus

    first = lughus.LLM
    assert "LLM" in vars(lughus), "resolved symbol should be cached in module globals"
    assert lughus.LLM is first


def test_every_exported_name_resolves() -> None:
    """Catches an __all__ entry missing from _LAZY_ATTRS.

    Without this, a forgotten mapping produces an AttributeError for the user and
    nothing fails in CI.
    """
    import lughus

    unresolved = [name for name in lughus.__all__ if getattr(lughus, name, None) is None]
    assert unresolved == [], unresolved


def test_dir_reports_the_public_surface() -> None:
    import lughus

    assert sorted(lughus.__all__) == dir(lughus)
