# Replay and evaluations

A replay bundle is sealed with SHA-256 after sensitive values have been removed. Integrity detects
accidental or malicious modification; it does not encrypt the bundle. Strict replay substitutes all
external calls with recorded responses. Scenario evaluation asserts terminal state, required and
forbidden events, sequence order and event budget. Probabilistic quality scores should run in a
separate sampled suite and must not make a single unstable call a merge gate.
