> [← Documentation index](index.md)

# Compatibility Policy

Lughus follows Semantic Versioning 2.0 (SemVer).

- **Patch releases (`x.y.Z`)**: Bug fixes, security corrections, and non-breaking optimizations.
- **Minor releases (`x.Y.0`)**: Backward-compatible additive features and contract extensions.
- **Major releases (`X.0.0`)**: Breaking changes or deprecation removals.
- **Event Schemas**: Event schemas are independently versioned via `SCHEMA_VERSION`. Wire additions remain backward-compatible.
- **Security Updates**: Security fixes may reject previously accepted unsafe configurations to protect production systems.
