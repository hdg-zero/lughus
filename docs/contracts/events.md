# Run event contract v1

Events have stable `event_id`, `run_id`, monotonic `sequence`, UTC timestamp, visibility and
schema version. Public consumers ignore unknown event types and optional fields. Event order is
per run, not globally. Terminal run states are immutable. Internal/model/audit events must be
projected deliberately before crossing an API boundary.
