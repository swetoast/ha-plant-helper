# Contributing to Plant Helper

Thank you for helping improve Plant Helper. Contributions should preserve the integration's existing Home Assistant contracts and remain focused on clear end-user value.

## Before opening an issue

Search existing issues first. For a bug, include:

- Plant Helper version
- Home Assistant version
- Installation method
- Reproduction steps
- Expected and actual behavior
- Relevant sanitized logs
- Screenshots when the problem is visible in the interface

Do not include API keys, access tokens, private addresses, or other credentials.

## Development setup

1. Fork and clone the repository.
2. Create a focused branch from the current default branch.
3. Make the smallest cohesive change that solves the problem.
4. Add or update tests for the affected behavior.
5. Update user documentation and the changelog when behavior or configuration changes.
6. Run the complete test suite from the repository root:

```bash
pytest -q
```

The project test foundation is described in `docs/TEST_FOUNDATION.md`.

## Code expectations

- Preserve existing entity IDs, state types, units, device classes, state classes, availability behavior, and useful attributes unless a breaking change is explicitly agreed.
- Keep configuration and options flows compatible with the supported Home Assistant release.
- Keep provider failures isolated. One unavailable external service must not prevent sensor-based plant monitoring from updating.
- Treat provider content as read-only context. It must not overwrite configured sensors or silently replace learned care behavior.
- Use cohesive modules and shared logic. Add a new file only for a substantial, distinct subsystem.
- Avoid unrelated refactoring in a focused bug fix.
- Never commit secrets, personal data, local addresses, or private fixture content.

## Tests

Changes must include behavioral coverage appropriate to their scope. Important areas include:

- integration setup, reload, unload, and removal
- configuration and options forms
- public sensor and binary-sensor contracts
- persistence and migration
- care calculations and precedence
- external provider parsing, transport failures, plan restrictions, and rate limits
- malformed, missing, empty, and unavailable source data
- release packaging and documentation consistency

When changing a production module or public top-level definition, update the foundation inventory and its behavioral tests.

## Documentation

Documentation must describe the current component rather than historical implementation phases. Write for end users, use generic examples, and do not include personal deployment details. Keep visible headings and labels in sentence case and do not use emojis.

Update these files when relevant:

- `README.md` for installation, configuration, behavior, entities, and services
- `CHANGELOG.md` for user-visible release changes
- `docs/TEST_FOUNDATION.md` for test-structure changes
- issue templates when requested diagnostic information changes
- `strings.json` and translations when configuration labels or descriptions change

## Pull requests

A pull request should:

- explain the problem and the chosen solution
- list user-visible changes
- describe tests performed
- identify any unverified behavior
- avoid bundling unrelated changes
- contain no generated caches or local development files

Use concise commit messages such as `Fix global settings selector` or `Update Perenual access documentation`.
