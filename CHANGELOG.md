# Changelog

## 0.0.30 - 2026-09-23

- Seasonal dormancy (F4): a dormant plant now tolerates wet soil longer instead of being nagged. Dormancy is read from signals already computed per plant (outdoor `growth_season`, indoor `season` / `day_length`) and applied as a multiplier on the drying coefficient, so a resting plant's tolerated wet period lengthens through the existing coefficient machinery rather than a parallel path. The new `dormant` attribute on `sensor.<plant>_status` shows when a plant is being judged as dormant, and `drying_context` reflects the slower expected drying.
- Two deliberate safety bounds: the seasonal effect is clamped like the drying coefficient, so extreme waterlogging still escalates to too_wet even in deep dormancy; and dormancy relaxes only the wet (overwatering) side, which is the real dormancy-season risk. A genuinely dry plant still reads needs_water in any season, so a resting plant is never left to go thirsty.
- Implementation note vs the roadmap: dormancy adjusts the wet allowance rather than also widening needs_water patience, because suppressing a real dryness signal in winter is the more dangerous failure. This is the safer reading of the roadmap intent.
- This completes the F1-F4 feature roadmap (species photos, light and humidity tracking, learned per-plant baselines, seasonal dormancy).

## 0.0.29 - 2026-09-23

- Learned per-plant baselines (F3): each plant now learns its own comfortable moisture range from how it actually behaves, and once calibrated the engine judges against that instead of the generic profile band. A plant that likes it wet can read needs_water at 38% while another reads wet at the same value; the profile becomes the seed and fallback, not the law.
- How it learns: the new `domain/temporal/baseline.py` accumulates the troughs a plant is allowed to reach before watering and the peaks it reaches just after, across watering cycles. Calibration completes only after 14 days of coverage with at least two full cycles at high confidence, and the learned band is clamped so a stuck or noisy sensor can never teach a nonsense range. Accumulated samples and the finished baseline persist through the existing store and survive restarts.
- The `sensor.<plant>_calibration` entity now reports `learning` while it gathers evidence and `calibrated` once the learned band is in effect (previously it reported `source_sensor`). This is the indicator of whether a plant is judged by its learned range or the profile.
- Moving a plant (placement change) or changing its species to a different taxon relearns the baseline; an alias species change keeps it.
- Roadmap deviation, noted: persistence uses the existing `PlantHelperStorage` learned/active-samples layer (which was already built for exactly this) rather than bumping the temporal store to v2, avoiding a duplicate store. The whole learning path is defensively wrapped: any learning failure falls back to the profile band, so the core evaluation cannot break.

## 0.0.28 - 2026-09-23

- Light and humidity tracking (F2): light and humidity now get the same trend-aware treatment as soil moisture, for both indoor and outdoor plants. Each is judged on a rolling mean (a day-long window for light, a shorter one for humidity) and reported as low / adequate / high in the new `light_context` and `humidity_context` attributes on `sensor.<plant>_status`.
- Sustained inadequate light or humidity now lifts `sensor.<plant>_health` to `watch`, but never raises needs_attention: moisture remains the only signal that flags a plant for action, and a moisture alarm (or a missing moisture reading) always wins over the secondary signals. Verdicts only form once enough valid samples exist, so a sparse sensor never drives them.
- `PlantObservation` now carries light and humidity alongside moisture and soil temperature in the one rolling history per plant, and they persist and restore through the temporal store.
- Implementation note vs the roadmap: light adequacy uses a rolling mean rather than a per-local-day integral. The integral would pull timezone/local-day handling in for marginal benefit in this first cut; the low/adequate/high outcome is identical. The `DailySummary` scaffold remains for a later integral-based refinement.

## 0.0.27 - 2026-09-23

- Added a feature roadmap (`docs/design/feature_roadmap.md`) that pre-decides the design of the next four features (species photos, light and humidity tracking, learned per-plant baselines, seasonal dormancy) so each can be built without re-litigating decisions.
- Species photos (F1): wired the existing security-hardened image proxy end to end. `sensor.<plant>_species` now shows a real photo via its `image_url` attribute, served from a local authenticated endpoint (`/api/plant_helper/image/<digest>`) rather than a raw provider URL. The proxy fetches, SSRF-validates, thumbnails to WEBP, caches, and serves the image; enrichment triggers the refresh, and a daily timer garbage-collects unreferenced thumbnails.
- On any image failure the raw provider URL is deliberately never surfaced; the plant simply shows no photo until the next successful refresh. The image endpoint requires authentication.
- No behavior change to any existing entity state; this only populates the previously reserved `image_url` attribute.

## 0.0.26 - 2026-09-23

- Removed the dead parallel flow architecture: `domain/setup_flow.py`, `domain/options_flow.py`, and `domain/reconfigure_flow.py`, plus their `tests/domain/test_flows.py`. These were pure, tested flow models that nothing wired: the live config flow is `config_flow.py` and the live options flow is `options.py` (which `config_flow` actually imports). They were dead and tested at once, which only gave false confidence about code that never ran.
- Removed two runtime dataclass fields that were never assigned or read: `learning` and `species_image_proxy`. The `learning.py` and `image_proxy.py` modules stay as scaffolding for the deferred learned-baselines and species-image features; only the dead placeholder slots are gone.
- No behavior change. `placement.py` and `runtime.handle_placement_change` were audited and kept: `placement.py` drives the edit-plant placement transition, and the hook is a deliberately empty wired stub, not dead code.

## 0.0.25 - 2026-09-23

- Fixed the status entity so it delivers context to both indoor and outdoor plants, which is what it was in the design for. `sensor.<plant>_status` now always carries `summary`, `reason`, `since`, `confidence`, `drying_context`, and `placement`, regardless of whether weather is configured. Outdoor plants additionally get `rain_suppression`, `frost_hours`, and `exposure`; indoor plants get `external_daylight`. Irrelevant attributes are dropped per plant rather than gating the whole set.
- Root cause of the 0.0.20 implementation being weak for indoor plants: the context was gated on a forecast being present and `drying_context` was computed only from the outdoor forecast, so indoor plants (which have no forecast) got almost nothing. `drying_context` is now derived from the temporal engine's drying coefficient, which is computed for both placements (evapotranspiration outdoor, soil temperature and humidity indoor), so the same word means the same thing on any plant. `confidence`, which the engine computes for every plant, is now surfaced too.
- This supersedes the 0.0.24 narrowing of the status entity to three attributes. The compact core (`summary`/`reason`/`since`) is kept and extended with the signals that are meaningful for every plant, and raw engine internals (drying rate, cycle peak, adjusted limit) still stay out of attributes.

## 0.0.24 - 2026-09-23

- Added the environmental drying coefficient (`domain/temporal/drying.py`). The wet-duration limit that decides `too_wet` is now scaled by expected drying instead of a flat 72 hours: fast-drying conditions shorten the allowance and slow-drying conditions extend it, bounded so a prediction can never shorten it by more than 35% or extend it by more than 100%. Outdoor plants are driven primarily by Open-Meteo reference evapotranspiration (`et0_24h`); indoor plants fall back to soil temperature and humidity. The persisted `adjusted_wet_duration_limit` records the limit actually used.
- The realized moisture slope still overrides the prediction: a soil that is measurably draining reads `drying` regardless of how aggressively conditions say it should have dried, so a shortened limit never overrules real drainage. All coefficients are starting values to tune against fixtures.
- Narrowed the status entity to the roadmap's compact attribute set: `sensor.<plant>_status` now exposes only `summary`, `reason`, and `since`, and no raw temporal state leaks into attributes. Status precedence is a single deterministic ordering in `domain/temporal/status.py`, and `needs_attention` is exactly the attention set of the status.
- BREAKING: this removes the weather attributes added to `sensor.<plant>_status` in 0.0.20 (`placement`, `rain_suppression`, `drying_context`, `frost_hours`, `exposure`, `external_daylight`). The weather still drives the status itself (outdoor rain still produces `watering_paused`); only the informational attributes are gone. If you want that context back on an entity, it belongs on a dedicated diagnostic sensor rather than cluttering the status.

## 0.0.23 - 2026-09-23

- Added persistence for the temporal soil engine. Rolling observations and moisture state now live in their own Home Assistant store (`plant_helper.temporal.<entry>`), separate from the config store. Writes are coalesced and debounced (flushed on a timer and on unload) rather than one write per reading. On restart the store is restored with timestamp validation: observations with a missing, naive, unparseable, or future timestamp are dropped, and state timestamps failing the same check reset to empty so duration timing resumes cleanly instead of trusting a bad clock. Restored data is pruned to plants that still exist.
- A run that predates the retained observation window still ages correctly: the persisted run start survives restart and window pruning, so a plant that was wet for days before a restart escalates rather than resetting to a fresh reading.
- Added a background evaluation tick (default 60 s, decoupled from the weather timer) that advances durations while moisture is unchanged. This is what makes `staying_wet` and `too_wet` reachable without waiting for the next sensor push. The tick records no observation and makes no provider or weather request, and it only notifies entities when the user-facing status actually changes.
- Removed `domain/storage_revision.py` and its re-exports. Its helpers had no call sites (plant-config concurrency is handled inline in `domain/storage.py`, which defines the `StorageConflictError` actually used), so this is dead-code removal, not a behavior change.

## 0.0.22 - 2026-09-23

- Introduced the temporal soil engine (`domain/temporal/`): a pure, clock-injected moisture interpreter that replaces the static per-reading band check. `sensor.<plant>_status`, `sensor.<plant>_health`, and `binary_sensor.<plant>_needs_attention` are now driven by an observation history and a wet/dry state machine rather than a single instantaneous reading. Raw measurement entities are unchanged.
- Fixed the long-standing false alarm where one elevated reading on a dry-profile plant (for example 47% against a 15-45 band) immediately read `too_wet`. A single elevated reading now reads `wet` with good health and no attention; escalation to `too_wet` requires sustained wetness beyond the drying limit with sufficient confidence. Rain suppression still folds in for outdoor plants, and critically dry soil still overrides it.
- BREAKING: the status string `water_soon` is renamed to `needs_water`. New status strings are also introduced (`recently_watered`, `wet`, `staying_wet`, `too_wet`, `drying`, `approaching_dry`, `too_dry`, and `waiting_for_data`), while `normal` and `watering_paused` are retained. Grep your automations and dashboards for `water_soon` before upgrading.
- Consolidated the test suite from 34 files into 10 foundational modules to keep the upload file count down, preserving the behavioral, structural, and packaging coverage.

## 0.0.21 - 2026-09-23

- Maintenance release. No runtime behavior change.
- Removed source-string snapshot tests that asserted implementation text rather than behavior and would break on any refactor. Kept and consolidated the behavioral, structural, and packaging checks. Manifest version is now validated only for self-consistency against the changelog, so a release bump touches one place instead of several.
- Added `docs/design/execution_roadmap.md`: a sequenced plan from the current release toward the full design, so temporal-sensor work and the remaining enrichment work proceed in order rather than scattered.

## 0.0.20 - 2026-09-23

- Wired Open-Meteo into the runtime. The forecast and air-quality collectors now run against the live Open-Meteo Forecast and Air Quality APIs through a new HTTP client and response adapter, so the previously unused collectors are connected.
- Added a periodic weather coordinator keyed off the configured update interval and the canonical coordinates (Plant Helper override or Home Assistant location). Forecast and air-quality caches self-throttle and refresh independently; a plant census decides whether the outdoor forecast and air-quality requests run.
- Plant evaluation now consumes the cached environment. Indoor plants use external daylight and seasonal context; outdoor plants gain rain suppression, drying context, frost, and exposure context. Physical moisture stays authoritative and critically dry soil still recommends watering regardless of forecast rain.
- The `sensor.<plant>_status` entity now exposes weather-derived attributes (placement, and for outdoor plants rain suppression, drying context, frost hours, and exposure; external daylight for indoor plants) when a forecast is available.

## 0.0.19 - 2026-09-23

- The species sensor now publishes the merged enrichment result. The iNaturalist to Trefle to Perenual chain already resolved identity and care data, but the entity only exposed the scientific name and family. The `sensor.<plant>_species` entity now also exposes common name, genus, watering category, and sunlight requirements as attributes when the providers return them.
- No change to the state value (the resolved scientific name), entity IDs, unique IDs, units, device classes, or storage schema. Provider, provenance, and other diagnostic fields remain internal.

## 0.0.18 - 2026-09-23

- Plant add, edit, and remove no longer overwrite global options with an empty set. The plant-management flow now returns the current options unchanged, so latitude, longitude, provider credentials, access level, and update interval survive plant changes.
- Plant management no longer triggers a full config-entry reload. Removed the entry update listener that reloaded on every options write; global reconfigure still reloads exactly once through the config flow.
- Stopped exposing raw third-party species image URLs as an entity attribute. The species entity no longer publishes a provider hotlink; the local authenticated image path remains reserved in the entity contract for a future release.
- Hygiene: replaced the star import in the config flow with explicit names, computed the entity unique ID once through the domain helper, and removed unused imports in the options, config, and storage modules.

## 0.0.17 - 2026-09-22

- Completed credential-aware provider activation and confirmed snake-plant alias resolution.
- Added provider request single-flight handling and updated enrichment cache policy constants.
- Preserved entity IDs, storage contracts, field-level provenance, and local image proxy behavior.

## 0.0.17 - 2026-09-22

- Removed the separate species input from plant setup.
- Use the plant name as the common-name lookup sent to iNaturalist.
- Show candidate selection when several species match and store the selected scientific identity internally.
- Accept exact scientific-name matches during later provider enrichment.

## 0.0.15 - 2026-09-22

- Removed the obsolete Home Assistant ozone sensor selector from setup and options.
- Made Open-Meteo the sole ozone source using the configured coordinates.
- Retained compatibility with existing entries by ignoring any legacy `ozone_entity` option.

## 0.0.14 - 2026-09-22

- Resolve the optional plant name as a common name during add-plant setup.
- Show a species-selection step when iNaturalist returns multiple candidates, then store the selected scientific identity.
- Keep the configured common-name fallback available while provider resolution runs or fails.
- Reorganize tests by subsystem instead of keeping every regression and release check in the test root.

## 0.0.13 - 2026-09-22

- Added the chained species-provider workflow: iNaturalist common-name discovery, Trefle taxonomy resolution, and Perenual care-data fallbacks.
- Preserved resolved species context across later sensor evaluations and refreshed stored plants during startup.
- Reloaded the integration when global provider options change.
- Added recorded provider fixtures and regression tests for empty, ambiguous, synonym, and multiple-candidate responses.

## 0.0.12 - 2026-09-22

- Added a humidity entity for each plant with a configured humidity source.
- Added a battery entity that preserves verified categorical states (`high`, `middle`, `low`) or numeric values from 0 through 100.
- Improved the calibration entity so it clearly reports `source_sensor` instead of implying that setup was incomplete.
- Replaced the meaningless calibration progress value with a concise explanation that Plant Helper uses the selected source sensor's calibrated reading.
- Preserved all existing entity keys and added the new entities without renaming or replacing existing entities.
- Added regression coverage for the humidity contract, mixed battery contract, calibration meaning, and entity-key preservation.

## 0.0.11 - 2026-09-22

- Fixed Home Assistant entity setup crashes caused by assigning Plant Helper's internal `EntityContract` as `entity_description`.
- Kept the internal contract separate while continuing to apply names, icons, units, device classes, and state classes directly to entities.
- Prevented plant-device deletion while any entity-registry record, including a template entity, still references the device.
- Restricted categorical battery states to the verified `high`, `middle`, and `low` values while retaining numeric values from 0 through 100.
- Added regressions for Home Assistant entity-description compatibility, referenced-device retention, and the exact battery state contract.

## 0.0.10 - 2026-09-22

- Fixed the battery-source regression introduced by restricting the selector to numeric battery device-class sensors.
- Restored support for soil sensors that expose categorical battery states such as `middle`.
- Preserved numeric battery percentages as numbers and categorical battery states as source values without inventing percentages.
- Kept unavailable, unknown, empty, and unsupported battery values unavailable.
- Added fixture-backed regression tests for both real soil-sensor battery formats.

## 0.0.9 - 2026-09-22

- Reworked add, edit, and remove lifecycle handling around durable storage commits.
- Fixed removal failures caused by post-commit entity and registry cleanup being reported as if the plant still existed.
- Added idempotent removal cleanup with persisted progress and automatic retry during integration setup.
- Moved removal ownership into the runtime lifecycle coordinator instead of the options form.
- Removed loaded entities safely, including entities still waiting to be attached by Home Assistant.
- Scoped entity-registry cleanup to the current config entry and exact plant unique-ID prefix.
- Required the removal confirmation checkbox and handled empty plant lists.
- Prevented post-commit add and edit activation failures from producing false save-failure messages.
- Added lifecycle foundation tests for durable removal, retry after restart, confirmation, and setup ordering.

## 0.0.8 - 2026-09-22

- Fixed Add Plant reporting failure after the plant had already been persisted and created.
- Prevented newly queued entities from writing state before Home Assistant has attached them to the entity platform.
- Restricted the soil-moisture selector to moisture sensors and the battery selector to numeric battery sensors.
- Added regression coverage for the asynchronous entity-creation race observed in Home Assistant.

## 0.0.7 - 2026-09-22

- Added sanitized Open-Meteo, Perenual, and Trefle regression fixtures from real provider responses.
- Added real forecast coverage for rain accumulation, wet hours, ET0, radiation, timezone metadata, surface soil temperature, and modelled surface soil moisture.
- Kept modelled Open-Meteo soil moisture separate from the physical plant moisture percentage entity.
- Updated Perenual handling to accept both search lists and single details objects.
- Distinguished Perenual paid-plan restrictions from ordinary not-found responses.
- Updated Trefle handling to accept a single species details object.
- Added tests for inconsistent Trefle summary metadata, categorized images, nullable botanical fields, and sanitized provider data.

## 0.0.6 - 2026-09-22

- Added sanitized regression fixtures from two real Home Assistant soil-sensor devices.
- Added coverage for numeric moisture, temperature, humidity, illuminance, and battery readings.
- Added coverage ensuring categorical battery states are not misreported as numeric percentages.
- Preserved calibration, sampling, warning, link-quality, dry-state, and temperature-unit evidence without treating those control entities as plant measurements.

## 0.0.5 - 2026-09-22

- Connected configured physical source entities to the Plant Helper runtime.
- Seeded current moisture, temperature, light, humidity, and battery values during startup.
- Added live state-change subscriptions and debounced reevaluation.
- Added functional status, health, calibration, species, and attention states without changing entity IDs or the entity contract.
- Added real listener, task, entity-registry, device-registry, and unload cleanup.
- Preserved optional provider isolation so enrichment failures cannot break core plant monitoring.

## 0.0.4 - 2026-09-22

- Fixed plants being created without sensor or binary-sensor entities.
- Entity platforms now reconcile persisted plants directly during setup.
- Add Plant now explicitly asks every loaded platform to create the new plant entities after persistence.
- Entity creation is idempotent, so runtime notifications and explicit reconciliation cannot create duplicates.

## 0.0.3 - 2026-09-22

- Fixed Add plant failing because the runtime storage backend was never created or loaded.
- Runtime storage now loads before sensor and binary-sensor platforms are forwarded.
- Existing stored plants are restored into the runtime collection during setup.
- Added safe operational defaults for optional runtime hooks used by plant management.
- Added server-side exception logging for unexpected Add plant failures.

## 0.0.2 - 2026-09-22

- Fixed HACS installation packaging so all runtime domain modules are installed inside `custom_components/plant_helper`.
- Fixed the Home Assistant config-flow import failure reported as `Invalid handler specified`.
- Added isolated-package tests that import the integration and config flow without repository-root helper packages.

## 0.0.1 - 2026-09-22

Initial GitHub and HACS repository release.

- Added shared configuration and reconfigure flows.
- Added revision-safe persistent storage.
- Added dynamic add, edit, and remove plant flows.
- Added event-driven physical sensor processing.
- Added learning and placement runtime behavior.
- Added forecast and air-quality collectors with stale-data preservation.
- Added indoor and outdoor interpretation.
- Added optional Perenual, Trefle, and iNaturalist species enrichment.
- Added HTTPS-only authenticated species-image proxy with SSRF protection, image limits, thumbnails, content-addressed caching, ETags, garbage collection, and stale-image preservation.
- Added the final compact entity contract with seven sensors and one problem binary sensor per plant.
- Added cumulative integration, privacy, translation, manifest, compile, and packaging verification.
- Added HACS metadata, GitHub validation workflows, brand assets, public documentation cleanup, and the post-release maintenance plan.
