# ADR-002: Streaming and retries

Status: accepted

Two explicit semantics are supported: buffered/retry-safe and live/at-most-once. In live
mode retries are allowed only before the first public delta. After emission, failures are
terminal events carrying partial-result metadata; content is never replayed transparently.
