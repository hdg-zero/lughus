# Patch-series validation record

Authoring environment: Python 3.14.6 with a restricted, preinstalled library set.
The project targets Python >=3.11. All Python source/test files were additionally
parsed using the Python 3.11 AST grammar. No dependencies were installed here.

Executed against the final 0.21 tree:

| Suite | Tests | Scope |
|---|---:|---|
| test_runtime_v019.py | 3 | Context propagation, exclusive gate, cancelled writer |
| test_code_interpreter.py | 5 | Configuration, fail-closed engine absence, OCI flags, envelope and files |
| test_http_v020.py | 3 | Same-origin policy, multiline SSE, bounded framing |
| test_sqlite_v021.py | 7 | Real transactions, owners, receipts, approvals, budgets, process crash |

These 18 stdlib tests pass. No live container is used by the interpreter contract
tests. The SQLite crash test launches a real child and deliberately exits it
without normal cleanup after committing a started action.

Additional local diagnostics exercised public run/stream suspend/approve/resume,
early stream closure, unknown-effect reconciliation, and a real MCP stdio child
with large stderr. Those diagnostics replaced third-party telemetry/schema/HTTP
dependencies with doubles; they do NOT establish library integration correctness.

NOT executed here: full pytest/coverage, Ruff, Mypy, Pydantic integration, wheel
installation, native HTTP interoperability, a Docker/Podman daemon, malicious-code
containment against a live worker, multi-version Python CI or performance tests.
Do not interpret this branch as already CI-green or production-certified.

Before pushing each branch, run scripts/verify_beta_release.sh (available on 0.21;
use the equivalent commands on 0.19/0.20). Formatting/type/coverage findings still
need to be resolved in the normal development environment. Update api_snapshot.json
with scripts/update_api_snapshot.py after reviewing the intentional public changes.
Run live containers with a verified image digest and test timeouts, orphan cleanup,
network denial, output floods and persistent artifacts. Test A2A against the target
0.3 server and MCP against each supported transport using real HTTP streaming.
