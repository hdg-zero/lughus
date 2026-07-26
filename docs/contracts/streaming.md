# Streaming delivery

`buffered` preserves retry-safe 0.1 behavior. `live` emits each provider delta immediately.
Retries in live mode stop after the first public delta; a later provider error is terminal and
already-emitted content is not replayed. Tool calls execute only after their complete arguments
have been assembled and validated.
