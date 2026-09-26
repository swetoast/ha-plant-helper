# Post-release maintenance plan

This plan starts after the first public GitHub and HACS release. Maintenance work should preserve the existing entity contract, plant UUIDs, storage behavior, and user configuration unless a documented migration is included.

## Release policy

- Use semantic versioning.
- Patch releases contain compatible bug fixes, documentation corrections, dependency updates, and translation fixes.
- Minor releases may add backward-compatible capabilities or optional entities when those entities provide clear user value.
- Major releases are reserved for intentionally incompatible storage, configuration, or entity-contract changes.
- Keep `manifest.json`, the Git tag, the GitHub release title, and the changelog version aligned.
- Publish a full GitHub release after validation succeeds. Do not publish from an untested working tree.

## Supported branch workflow

- `main` contains the current supported release line.
- Use short-lived branches for fixes and planned features.
- Require the HACS and Hassfest workflows to pass before merging.
- Keep unrelated refactoring out of urgent patch releases.

## Routine maintenance

### Monthly

- Review open issues and reproducible error reports.
- Review Home Assistant deprecations affecting config flows, entities, selectors, storage, HTTP views, and registries.
- Review HACS publishing requirements and validation changes.
- Check optional provider behavior, quotas, authentication errors, and response-contract changes.
- Review automated dependency and workflow-action updates.

### Before each Home Assistant release cycle

- Run the complete local test suite against the supported Home Assistant test environment.
- Verify setup, reconfigure, add, edit, remove, reload, and uninstall behavior.
- Verify dynamic entity and device registry cleanup.
- Verify translations and manifest metadata.
- Verify that provider or debug details are not exposed as entity states or attributes.

### Quarterly

- Exercise forecast, air-quality, species, and image paths with current provider responses.
- Review SSRF protections, redirect validation, image limits, cache cleanup, and authenticated image serving.
- Review storage migration readiness and recovery behavior.
- Remove obsolete compatibility code only after the minimum supported Home Assistant version has advanced.

## Issue handling

1. Reproduce the report with the released source.
2. Classify the issue as security, data loss, regression, provider compatibility, Home Assistant compatibility, or normal defect.
3. Add a regression test before or with the fix when practical.
4. Preserve stable unique IDs, entity IDs, units, device classes, state classes, and availability behavior.
5. Document user-visible changes in `CHANGELOG.md`.

Security issues, credential exposure, destructive storage behavior, SSRF bypasses, or unauthorized image access take priority over routine feature work.

## Provider maintenance

- Keep provider adapters isolated from the entity contract.
- Preserve stale valid enrichment and image data when refresh fails.
- Treat authentication suspension and rate limits as provider-specific conditions, not complete integration failure.
- Redact secrets from exceptions, logs, diagnostics, tests, and issue examples.
- Do not expose provider names or raw provider payloads as normal entity attributes.

## Release checklist

1. Update the version in `custom_components/plant_helper/manifest.json`.
2. Update `CHANGELOG.md` with the release date and user-visible changes.
3. Confirm repository URLs and code owners in `manifest.json`.
4. Run the complete test suite with no required tests skipped.
5. Compile all Python sources.
6. Confirm `strings.json` and `translations/en.json` remain aligned.
7. Run HACS validation and Hassfest through GitHub Actions.
8. Inspect the repository for credentials, private addresses, local paths, caches, and generated files.
9. Create a Git tag matching the manifest version.
10. Create a full GitHub release from that tag.
11. Install the release through HACS as a custom repository and perform a smoke test.

## Smoke test

- Install through HACS and restart Home Assistant.
- Create the integration entry.
- Add one indoor and one outdoor plant, walking each configured species
  provider step (pick a record on one, skip another).
- Confirm entity creation, names, units, device classes, and availability,
  including `image.<plant>` once a photo is fetched.
- Edit each plant and confirm identity and the chosen species records are
  retained.
- Re-match one plant's species data and confirm the species sensor updates.
- On a free Perenual key, confirm paid-only records are not offered.
- Remove both plants and confirm entity and device cleanup.
- Remove and reinstall the integration while preserving expected Home Assistant storage behavior.
