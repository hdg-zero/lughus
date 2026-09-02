> [← Documentation index](index.md)

# Production readiness

`/health` is liveness only. Deployments must add readiness checks for their persistent store
and required providers. TLS, distributed rate limits and body size are enforced at ingress as
well as in process. Production requires API authentication, a public URL, disabled test UI and
a task store declaring durable capabilities.
