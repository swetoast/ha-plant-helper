# Plant Helper Quality Roadmap

This roadmap is the release-quality tracker for Plant Helper. Completed work is checked off in the same revision that implements and verifies it.

## Phase A: Runtime correctness

- [x] Allow Trefle search and detail requests to complete within one provider lookup.
- [x] Allow iNaturalist taxon and fallback-photo requests to complete within one lookup.
- [x] Report actual provider HTTP call counts.
- [x] Apply the configured coordinator update interval.
- [x] Honor the initial radiation-source selection.
- [x] Preserve source timestamps and reject stale local telemetry.
- [x] Correct the destructive remove-plant description.
- [x] Add Phase A regression tests.

## Phase B: Home Assistant boundary and lifecycle verification

- [x] Verify the complete config-flow and options-flow lifecycle contract.
- [x] Verify options changes use one revision-driven reload path.
- [x] Verify plant removal purges storage, learned data, samples, coordinator state, entities, and the device.
- [x] Verify unload flushes only debounced stores and cannot resurrect removed plants.
- [x] Verify service registration matches `services.yaml` and translation metadata.
- [x] Verify coordinator per-plant failure isolation.
- [x] Verify coordinator save scheduling and day-boundary markers.
- [x] Verify global runtime settings reach the coordinator.
- [x] Verify local telemetry freshness uses Home Assistant source timestamps.
- [x] Verify STRÅNG and enrichment network work remains off the critical update path.
- [x] Verify manifest, strings, and English translation contracts.
- [x] Add HTTP-workflow tests for Trefle and iNaturalist multi-call operations.
- [x] Verify daily provider limits prevent network calls and report zero actual calls.
- [x] Run the complete existing suite plus Phase B tests.
- [x] Compile the complete source tree and verify all relative imports.

## Phase C: Source and lifecycle hardening

- [x] Make direct STRÅNG fallback retryable after temporary failures.
- [x] Add radiation-source diagnostics.
- [x] Standardize provider-health state and partial-result reporting.
- [x] Remove the obsolete duplicate enrichment implementation if no live consumer remains.
- [x] Harden global service registration and removal lifecycle.
- [x] Apply privacy-safe public author metadata.

## Phase D: Documentation and release cleanup

- [x] Synchronize README configuration fields with the current config flow.
- [x] Synchronize the documented update interval with runtime behavior.
- [x] Document `plant_helper.refresh_species`.
- [x] Correct Health sensor behavior during calibration.
- [x] Remove manually maintained assertion counts from release-facing documentation.
- [x] Update production-readiness wording to distinguish completed automated verification from pending live Home Assistant verification.

## Phase E: Operational resilience

- [x] Prevent overlapping STRÅNG refresh tasks.
- [x] Prevent overlapping enrichment refresh tasks.
- [x] Cancel and drain background tasks during config-entry unload.
- [x] Retry temporary STRÅNG failures on the next coordinator cycle instead of waiting one hour.
- [x] Register global services independently and idempotently.
- [x] Expose the complete standardized provider-health diagnostic contract.
- [x] Add Phase E regression tests and rerun the complete source-test suite.

## Phase F: Real sensor compatibility

- [x] Verify native `moisture` and legacy `humidity` device classes remain selectable for soil moisture.
- [x] Verify temperature and illuminance selectors match real Home Assistant sensor classes.
- [x] Keep categorical battery sensors selectable even when they have no battery device class.
- [x] Accept numeric battery states with a trailing percent sign and categorical `middle` states.
- [x] Verify 30-second and 600-second source update timestamps remain fresh under the runtime validation window.
- [x] Expose linked Home Assistant source entities on the existing Sensor fault diagnostic.
- [x] Add regression coverage based on the supplied Soil Sensor and Soil Sensor 2 entity patterns.



### Phase H: Learning lifecycle completion
- [x] Define the post-calibration adaptation policy.
- [x] Wire conservative M_max-only adaptation from qualified post-lock daily evidence.
- [x] Keep drying rate, DLI, window transmission, and thermal constants locked pending dedicated bounded policies.
- [x] Detect placement changes in the options flow.
- [x] Preserve independent indoor and outdoor baselines.
- [x] Clear local samples and condition timers when placement changes.
- [x] Reuse a complete target-placement baseline or resume calibration when absent.
- [x] Add behavioral tests for adaptation and placement transitions.
- [ ] Complete a live Home Assistant lifecycle test of placement changes and post-lock adaptation.

- [x] Make the placement transition decision load-bearing in the options flow.
- [x] Initialize or resume target-placement calibration when no complete baseline exists.
- [x] Reuse a complete target-placement baseline without resetting its learned state.
- [x] Persist standard/custom dry-threshold policy metadata in locked baselines.
- [x] Recompute adapted M_dry from the persisted policy with a legacy migration fallback.
- [x] Add the twelve-stage learning lifecycle map and live-test checklist.


### Repository release readiness
- [x] Provide HACS custom-repository metadata.
- [x] Document HACS and manual installation.
- [x] Document configuration, services, removal, support, and learning behavior.
- [x] Document verification scope and the remaining live lifecycle gate.
- [x] Keep official certification and live verification claims distinct.
- [ ] Complete the live Home Assistant lifecycle checklist.
- [ ] Add final brand assets before default HACS catalogue submission.
