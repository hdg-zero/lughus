> [← Documentation index](../index.md)

# Releasing Lughus

## Automated pipeline

`.github/workflows/publish.yml` triggers on a published GitHub release and runs:

```
verify (reuses ci.yml)  ->  guard (tag == project.version)  ->  publish (environment: pypi)
```

Three core properties govern the release process:

1. **Verification precedes publication.** Publishing to PyPI is irreversible: a
   deleted version can never be republished under the same number. `verify`
   reuses `ci.yml` through `workflow_call` rather than duplicating its steps,
   because two divergent definitions of "verified" eventually produce an
   unverified release.
2. **The published artefact is the tested artefact.** `publish` downloads the
   `dist` artefact that CI built and that `dist-core` and `extras` exercised. It
   does not rebuild.
3. **Every action is pinned by commit SHA**, including
   `pypa/gh-action-pypi-publish`, guaranteeing reproducible and auditable releases.

## One-time manual setup (not verifiable from the repository)

These live in GitHub and PyPI settings, so no commit can assert them. Check them
off once:

- [ ] Create the **`pypi` environment** in repository settings, with required
      reviewers. Without it, `environment: pypi` grants no protection and the OIDC
      token is not gated.
- [ ] Configure the **PyPI trusted publisher** for the project, targeting this
      repository, the `publish.yml` workflow, **and** the `pypi` environment.
- [ ] Enable **branch protection** on `main`, requiring the `gate` check.
- [ ] Enable **Dependabot** for `github-actions` and `pip`, grouped.
- [ ] After the first release: confirm the **attestations** are visible on the
      PyPI project page.

## Release checklist

1. `uv lock` and commit the lockfile if dependencies changed. CI's
   `uv lock --check` fails otherwise, by design.
2. Bump `project.version` in `pyproject.toml`.
3. Move the `[Unreleased]` section of `CHANGELOG.md` under the new version, with a
   dated heading. Every breaking change needs one actionable migration line.
4. Confirm `docs/` matches the behaviour being shipped. A false document is worse
   than a missing one.
5. Tag `vX.Y.Z` and publish the GitHub release. The tag must match
   `project.version` or `guard` refuses to publish.
