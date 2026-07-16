---
type: API Reference
title: Server API
description: API reference for the serve entrypoint function.
---

# Server API

The `server` module provides `build_app()` for ASGI integration and `serve()` as the quickstart Uvicorn runner.

## `build_app`

Builds an A2A Starlette application without starting Uvicorn.

```python
def build_app(
    agent_card: AgentCard,
    gateway: BaseGateway,
    *,
    task_store: TaskStore | None = None,
    setup_otel: bool = True,
    enable_test_ui: bool = False,
) -> object:
```

Returns the Starlette-compatible ASGI application built by the A2A SDK. Use this when deploying through your own ASGI stack, adding middleware, or testing the app directly.

### Parameters
*   `agent_card`: The `AgentCard` metadata object defining agent credentials, default input/output modes, version, and capabilities.
*   `gateway`: The [BaseGateway](gateway.md) instance that contains the executor logic.
*   `task_store`: Custom persistent `TaskStore` instance. If `None`, defaults to `BoundedInMemoryTaskStore` using `TASK_STORE_TTL_SECONDS` and `TASK_STORE_MAX_TASKS`, and logs a production warning.
*   `setup_otel`: If `True`, automatically configures standard OpenTelemetry exporters (traces and metrics). Set to `False` if your parent application already sets up custom OTel providers.
*   `enable_test_ui`: If `True`, exposes a local testing interface at `/ui` and a JSON run endpoint at `/ui/run`.

`build_app()` also installs `ProductionGuardMiddleware`, which enforces `MAX_HTTP_BODY_BYTES`, optional per-worker request backpressure through `MAX_CONCURRENT_REQUESTS` / `MAX_QUEUE_BACKLOG`, and, when `API_BEARER_TOKEN` is set (supports multiple comma-separated keys), timing-safe bearer-token auth on non-health routes. If `CORS_ORIGINS` is set, `build_app()` configures Starlette `CORSMiddleware`. When `LUGHUS_ENV=production`, `build_app()` fails fast unless `PUBLIC_URL`, `API_BEARER_TOKEN`, and a custom persistent `task_store` are configured and the test UI is disabled.

## `serve`

Starts an A2A JSON-RPC server.

```python
def serve(
    agent_card: AgentCard,
    gateway: BaseGateway,
    host: str = "0.0.0.0",
    port: int = 8080,
    *,
    log_level: str = "INFO",
    task_store: TaskStore | None = None,
    setup_otel: bool = True,
    enable_test_ui: bool = False,
) -> None:
```

### Parameters
*   `agent_card`: The `AgentCard` metadata object defining agent credentials, default input/output modes, version, and capabilities.
*   `gateway`: The [BaseGateway](gateway.md) instance that contains the executor logic.
*   `host`: The host address to bind Uvicorn (default: `"0.0.0.0"`).
*   `port`: The port to listen on (default: `8080`).
*   `log_level`: Python and Uvicorn log level string (default: `"INFO"`).
*   `task_store`: Custom persistent `TaskStore` instance. If `None`, defaults to the bounded in-memory store. Use Redis, SQL, or another SDK-compatible persistent store for horizontally scaled deployments.
*   `setup_otel`: If `True`, automatically configures standard OpenTelemetry exporters (traces and metrics). Set to `False` if your parent application already sets up custom OTel providers.
*   `enable_test_ui`: If `True`, exposes a local testing interface at `/ui` and a JSON run endpoint at `/ui/run`.

## Test UI

> [!WARNING]
> La console de test locale est **strictement conçue comme un outil de développement et de débogage rapide en local**. Elle ne doit en aucun cas être exposée publiquement en production ou servir d'interface utilisateur finale.
> Si `LUGHUS_ENV=production`, l'application lèvera une erreur de validation au démarrage si la console est activée.

The test UI is disabled by default. Enable it only for local development or private test
deployments:

```python
serve(agent_card, gateway, enable_test_ui=True)
```

Then open:

```text
http://localhost:8080/ui
```

The UI sends an objective and optional files directly to `gateway.handle()`, then renders
`ProgressEvent`, `CompletionEvent`, tool call start/result events, and downloadable artifacts.
The browser consumes `/ui/stream` as newline-delimited JSON so progress and tool events appear live;
`/ui/run` remains available as a buffered JSON endpoint.
Tool call entries include the tool name, raw JSON arguments, duration, status, output, and error
type when applicable. It uses the same timeout, objective, file-size, and artifact limits from `BaseSettings`.

## `ProductionGuardMiddleware`

Small ASGI middleware used by `build_app()` and exported for custom stacks.

```python
ProductionGuardMiddleware(
    app,
    max_body_bytes=settings.max_http_body_bytes,
    bearer_token=settings.api_bearer_token,
    max_concurrent_requests=settings.max_concurrent_requests,
    max_queue_backlog=settings.max_queue_backlog,
    request_queue_timeout=settings.request_queue_timeout,
    gateway=gateway,
)
```

It rejects oversized request bodies with `413`, including streamed bodies without `Content-Length`, invalid bearer tokens with `401` (supports comma-separated list of multiple keys for timing-safe key rotation), and saturated workers or full request backlogs with `503` when request backpressure is enabled. It intercepts ASGI `lifespan.shutdown` events to call `gateway.shutdown()` for graceful task cancellation. `/health` and `/healthz` remain open for load balancers and orchestrators.
