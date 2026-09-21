# Changelog

## 4.4.9

- Replaced the initial setup form with a selector-free form to remove the complete schema serialization path from integration loading.
- Deferred single-instance checks until form submission.
- Fixed the fallback storage loader returning `None` after a successful load.
- Removed unresolved `PlantStorage` annotations from the options flow.
- Corrected remaining stale global-settings provider wording.


## 4.4.8

- Hardened the initial config flow and removed runtime-only result annotations.
- Replaced all literal number-selector modes with Home Assistant selector enums.
- Removed null suggested values and aligned setup translations with the schema.
- Kept latitude and longitude overrides in global settings, using Home Assistant location during initial setup.
- Removed wildcard constant imports and normalized persisted interval and coordinate values.
- Updated stale provider wording in the config flow and coordinator.


## [4.4.7] - 2026-09-21

### Fixed

- Made the integration package import-light so loading `config_flow.py` no longer imports the coordinator, storage, enrichment, API, or learning runtime first.
- Deferred runtime imports to setup and service execution, preventing unrelated runtime code from breaking the initial configuration form.
- Added regression coverage for the package-level import boundary.

## [4.4.6] - 2026-09-21

### Fixed

- Restored integration package and config-flow imports by importing `dataclass` before the coordinator's `_MacroReading` declaration.
- Added regression coverage requiring the coordinator's dataclass decorator import.

## [4.4.5] - 2026-09-21

- Deferred storage, learned-state, and sample-store imports until the options actions that use them so the initial config-flow handler stays import-light.
- Removed the runtime dependency on `ConfigFlowResult`; it is imported only for static type checking.
- Made cleared latitude and longitude options fall back to Home Assistant location defaults.
- Removed obsolete STRÅNG and SMHI configuration text from the active implementation.

## [4.4.4] - 2026-09-21

### Fixed

- Restored config-flow loading on Home Assistant 2025.12 by using `ConfigFlowResult` from `homeassistant.config_entries` instead of the removed `FlowResult` import.
- Removed obsolete outdoor-source constants and unused coordinator constructor arguments.
- Added regression checks for config-flow imports, options-flow ownership, and coordinator/constant consistency.

## [4.4.3] - 2026-09-21

### Fixed

- Fixed the global configuration schema after removal of the legacy outdoor data-source selector.
- Added user-facing latitude and longitude labels to setup and options flows.
- Added regression coverage for configuration schema contracts and indoor/outdoor computation parity.
- Added outdoor vectors for rain suppression, forecast clearing, severe weather, ET0, and ozone behavior.

## [4.4.2] - 2026-09-21

### Changed

- Open-Meteo is now the always-on shared radiation and forecast provider.
- Uses Home Assistant coordinates by default with optional latitude and longitude overrides.
- Requests 72 forecast hours with models=auto.
- Legacy provider selectors are removed and stored legacy options are ignored.
- Model-grid soil values are no longer requested.

# Changelog

## [4.4.1] - 2026-09-21

### Changed

- Limited Open-Meteo radiation requests to the values Plant Helper uses: hourly GHI for historical PAR and DLI, instantaneous GHI for current outdoor PAR and lux, and instantaneous DHI for diffuse-light and drying context.
- Kept indoor light assessment based on each plant's local lux sensor paired with the shared outdoor PAR baseline.
- Kept outdoor light assessment based on current horizontal GHI and the historical GHI-derived PAR series.
- Removed unused DNI, direct, GTI, terrestrial-radiation, STRÅNG, and SMHI radiation code instead of exposing unused diagnostics or inventing window orientation.


## [4.4.0] - 2026-09-21

### Changed

- Replaced the selectable radiation-source system with Open-Meteo as the sole radiation provider.
- Current plant calculations now use instantaneous shortwave, direct, diffuse, direct-normal, tilted, and terrestrial radiation values.
- Hourly averaged shortwave radiation remains the historical source for PAR-series and DLI integration.
- Removed radiation source and radiation entity options while preserving the existing radiation issue entity ID.


## [4.3.9] - 2026-09-21

### Fixed

- Separated the radiation-source selector from the optional radiation-entity picker in the configuration schema.
- Ignored the legacy invalid `radiation_entity: api` value so automatic Nordic operation uses the STRÅNG API instead of looking for an entity named `api`.
- Added regression tests for the corrected schema and legacy stored option.

## [4.3.8] - 2026-09-21

- Prevented malformed or legacy nested plant configuration from crashing integration setup.
- Rejected non-finite, invalid, and out-of-range persisted numeric values before they reach the runtime engine.
- Added lifecycle regression coverage for malformed persisted plant records.


All notable changes to Plant Helper will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [4.3.7] - 2026-09-21

### Fixed

- Validated nested runtime-sample records before accepting persisted data, preventing delayed crashes from malformed series or reading entries.
- Validated every learned plant record before accepting the learned store, preserving the existing fail-safe behavior instead of allowing malformed records into runtime logic.
- Stopped silently replacing malformed cached-plant or configured-plant mappings with empty dictionaries, which could otherwise erase recoverable stored data on the next save.

### Testing

- Added persistence regression checks covering malformed nested containers across all three storage layers.

## [4.3.6] - 2026-09-21

### Fixed

- Serialized HTTP requests per enrichment provider so simultaneous refreshes cannot bypass minimum-call intervals or race daily-limit counters.
- Rejected JSON arrays and scalar payloads before provider code attempts mapping operations.
- Sanitized provider exception diagnostics so exception text cannot expose API keys or other sensitive request details.
- Rejected non-finite and physically invalid light and thermal calibration inputs before they can poison learned baselines.
- Made plant and species entities unavailable when the coordinator's latest update fails instead of exposing stale values as current.

### Testing

- Added regression coverage for provider payload shape, exception sanitization, finite calibration input, and coordinator-aware entity availability.

## [4.3.5] - 2026-09-21

### Fixed

- Made the shared time-series sample boundary reject NaN and infinite values even when a caller incorrectly marks the sample valid.
- Excluded non-finite health pillars instead of allowing NaN to clamp into a false perfect score.
- Rejected non-finite ambient-humidity, ozone, and dormancy-trend inputs in their individual care models.
- Rejected negative ozone values as invalid source data.

### Testing

- Added regression coverage for non-finite values across time-series, health, humidity, air-quality, and dormancy models.

## [4.3.4] - 2026-09-21

### Fixed

- Rejected non-finite Home Assistant entity states and sun-elevation attributes before they enter plant calculations.
- Validated learned-store structure during loading so malformed persisted learning data cannot be silently replaced.
- Cleaned up the coordinator and partial runtime data when first refresh or entity-platform setup fails.
- Removed deleted plants from the entity registry before removing their device, preventing disabled or orphaned entities from surviving deletion.

### Testing

- Added regression coverage for partial setup cleanup, malformed learned storage, finite Home Assistant states, and complete registry cleanup.

## [4.3.3] - 2026-09-21

### Fixed

- Registered integration services during domain setup so service definitions remain available when no config entry is loaded.
- Kept services registered across config-entry unloads and retained actionable validation errors when the integration has no active runtime.
- Rejected non-finite numeric values such as NaN and infinity before they can enter sensor, forecast, or provider calculations.
- Limited ISO timestamp normalization to a trailing `Z` instead of rewriting arbitrary timestamp content.
- Changed persisted plant, learned, and sample storage loading to expose unreadable or malformed data instead of silently replacing it with empty state that could later overwrite valid history.
- Removed deleted plants from both the entity registry and device registry, in addition to clearing configuration, learned state, samples, and live coordinator data.
- Simplified the README release status so release history remains in the changelog.

### Testing

- Added regression coverage for service lifecycle, non-finite values, ISO parsing, storage failures, and complete plant removal.

## [4.3.2] - 2026-09-21

### Fixed

- Updated the options flow to use Home Assistant's provided `config_entry` property instead of retaining a manually injected private entry reference. This removes the deprecated options-flow pattern and keeps configuration editing compatible with Home Assistant 2025.12.
- Removed generated test caches and bytecode from the release package.
- Corrected release validation so the packaged archive, rather than only the working tree, is inspected and tested.

### Testing

- Added a regression test that rejects the deprecated private options-flow entry pattern.
- Re-ran the complete unit and contract suite after the compatibility repair.

## [4.3.1] - 2026-09-21

### Fixed

- Fixed the light-adequacy advisory (added in 4.3.0) being too aggressive, so it flagged healthy low-light plants such as snake plants as under-lit in a normal window. The species light floors were lowered to reflect real plant tolerance (a low-light plant genuinely survives well below a bright window), and the advisory now requires a real sample of bright-time observations before judging, so a single overcast reading or a thin buffer cannot trigger a false "under-lit". Validated against real side-by-side snake-plant sensors at 168 lx, which now correctly read as adequately lit while a genuinely dark spot or a light-hungry species is still flagged.

## [4.3.0] - 2026-09-05

### Added

- Added absolute light-adequacy advisory. The indoor light model measured window transmission and obstruction (whether light is blocked) but could not tell whether a location is bright enough for the species at all, so an unobstructed but fundamentally dark spot read as normal. It now compares the plant's own median bright-time indoor illuminance against a species light floor (derived from the light preference) and advises when the spot is too dim — catching the common "wrong location entirely" cause of slow decline. Advisory only; it never changes the health score or the care action. Surfaced on the Light entity as `species_light_adequacy` and on the Care action entity as `light_location_advisory`.
- Added an ambient-humidity advisory for humidity-loving indoor plants, using an optional air-humidity sensor (many soil probes already report one). It advises when the air is dry for a plant that prefers humidity, and stays silent for plants that do not (a succulent is never nagged) and for outdoor plants. Advisory only. Configured with a new optional humidity sensor and surfaced on the Care action entity as `humidity_advisory`.
- Added profile-weighted health. The health score now weights its moisture, light, and thermal pillars by the plant profile — a dry-tolerant plant weights light higher and is less penalised by dry soil, a moisture-loving plant weights moisture higher — so the score reflects what actually matters for that plant. The balanced profile keeps the previous weighting.

### Notes

- All three additions follow the "a say, not the wheel" principle: they are advisory context derived from species data and an existing sensor, and none of them override the plant's calibrated measured behaviour or alter a care action.

## [4.2.9] - 2026-09-05

### Fixed

- Fixed the Species enrichment showing another plant's data. The cache lookup used before an API call matched by substring, so a lookup for one plant returned a different cached plant whose species or common name merely contained the search text (for example "snake plant" matching "snake plant zeylanica", or "aloe" matching "aloe vera"). It now matches only an exact species or common name, so a plant can never display another plant's enrichment.
- Fixed enrichment staying blank after a failed lookup. A transient provider or network failure on the first attempt left the plant with no enrichment, and the daily refresh throttle meant it was not retried for up to a day. Plants that are not yet resolved are now retried on a short interval (fifteen minutes) with a forced provider lookup, while already-resolved plants continue to refresh once a day.

## [4.2.8] - 2026-09-05

### Added

- Added an optional radiation-sensor setting: point Plant Helper at an existing Home Assistant shortwave or global solar-radiation sensor in W/m² (for example the Open-Meteo Weather integration's "Solar Radiation" entity) and it becomes the radiation source. It is read each cycle, converted to photosynthetically active radiation, and used to build the light series — with the highest priority, so neither the STRÅNG API nor Plant Helper's own Open-Meteo fetch runs. This lets an installation that already pulls solar radiation reuse that data, avoids a second network dependency, and sidesteps STRÅNG entirely for users who prefer it. The active source reports as `radiation_entity`, and an unavailable sensor is reported rather than silently failing.

## [4.2.7] - 2026-09-05

### Fixed

- Fixed the STRÅNG radiation source repeatedly reporting a problem and the diagnostic entities flapping between "problem" and "unavailable". Three causes:
  - STRÅNG (and Open-Meteo) requests sent no `User-Agent` header. SMHI's open-data endpoints reject such requests with HTTP 403, so every fetch failed and the radiation source read as unusable. A descriptive User-Agent is now sent.
  - A failing STRÅNG fetch did not update its throttle timestamp, so it retried on every coordinator cycle instead of backing off. That per-cycle hammering can itself trigger HTTP 403 rate-limiting. The attempt is now throttled up front, with a shorter retry interval after a failure (ten minutes) than the normal hourly refresh, so a transient outage still recovers quickly without a request storm.
  - A Home Assistant forecast fetch that raised could fail the whole coordinator update and briefly mark every entity unavailable. The forecast fetch is now guarded so a hiccup degrades to no forecast instead of sinking the cycle.

### Testing

- Updated the STRÅNG resilience test to assert the failure backoff (shorter retry interval, throttled up front) rather than the previous per-cycle retry.

## [4.2.6] - 2026-09-05

### Fixed

- Fixed indoor light obstruction detection, which had been silently disabled since 4.2.1. When indoor pairing moved to the photosynthetically active radiation (PAR) reference, the calibration floor was converted to PAR units but the separate obstruction bright-light threshold was left as a lux value (1000). PAR values (roughly 0–400 W/m²) never reach it, so the "bright outside" test never became true and obstruction could never fire. The threshold is now in PAR units. Obstruction again flags a genuine disproportionate drop (bright outdoors, dark indoors) against the settled window baseline, while continuing to stay silent for an unobstructed window, an overcast day, and the provisional calibration period.

### Notes

- Churn audit of the 4.2.x line: verified no unused imports, no half-threaded engine fields, and no other lux-versus-PAR unit mismatches introduced by the PAR pairing change. The obstruction threshold above was the only such regression.

## [4.2.5] - 2026-09-05

### Added

- Added a diagnostic `reason` on the Temperature entity, mirroring the Light entity, so a thermal `unknown` state is explainable: `no_temp_data` when no soil-temperature sensor is linked (or its readings are invalid), `calibrating` while the normal temperature has not been learned yet, and `ok` when reporting a settled state.

### Notes

- Audited the temperature, moisture, battery, care-action, and health vectors against real Zigbee2MQTT soil-sensor values (moisture 96% and 46%, temperature 23.7°C and 22.4°C, battery `middle` and `100`). All behaved correctly: near-saturation moisture is not mistaken for overwatering, normal temperatures raise no false hazard (thermal hazard is weather-only by design), a categorical or percentage battery is read correctly while a critical battery pauses care, optional sensors absent degrade gracefully with health renormalising over the remaining pillars, and a calibrating plant raises no care nag.

## [4.2.4] - 2026-09-05

### Fixed

- Fixed the light obstruction check so it never complains about a plant that simply has an unobstructed window. Obstruction is a relative shortfall against the learned window baseline, so it is now only evaluated once that baseline is settled; while the window coefficient is still provisional during calibration, the light level is reported but no obstruction problem is raised. An overcast day (dim outdoors) already could not read as obstruction, and a stable no-blinds window continues to read as normal. Blinds remain entirely optional and inferred from light; there is no blinds entity to configure and none is required.

### Testing

- Added obstruction tests: a no-blinds normal day, an overcast day, and a provisional (calibrating) baseline all correctly report no obstruction, and the engine suppresses obstruction while light is provisional.

## [4.2.3] - 2026-09-05

### Added

- Added a diagnostic `reason` on the Light entity so a `none` state is explainable instead of silent. The reason distinguishes a missing light sensor (`no_light_sensor`), a missing radiation reference (`no_radiation_reference`), non-overlapping timestamps between the light and radiation series (`no_daylight_overlap`), a plant still gathering data (`calibrating`), and a working reading (`ok`). This resolves the ambiguity where a plant with no linked illuminance sensor looked identical to one that was merely still calibrating.

### Changed

- Changed the add-plant and edit-plant guidance to state that a light sensor is optional but that an indoor plant configured without one reports light as `no_light_sensor`, that outdoor plants need no light sensor because they use SMHI radiation, and that a single light sensor may be shared across nearby plants that occupy the same location.

### Notes

- Audited against real Zigbee2MQTT soil-sensor hardware. Confirmed: a categorical battery state such as `middle`, moisture near saturation, a dim indoor illuminance reading (around 500 lx), and device soil-sampling intervals of 30 and 600 seconds are all handled correctly. The two-hour sensor staleness window comfortably covers those sampling intervals, so readings are not treated as stale between device updates.
- A dim indoor illuminance reading produces a valid window-transmission reading; the indoor light score reflects transmission and obstruction relative to the window, not absolute species light requirements, so an unobstructed dim location can still read as adequate.

## [4.2.2] - 2026-09-02

### Added

- Added provisional indoor light during calibration. Once enough paired daylight observations exist, a live window-transmission coefficient is derived so the Light entity reports within a day instead of only after the full 14-day calibration completes. The reading is flagged with a `provisional` attribute so it is not mistaken for the settled value. Plants that were calibrated before the PAR change also report provisionally until they are recalibrated.

### Fixed

- Fixed reference evapotranspiration (ET0) drying being silently disabled whenever a Home Assistant forecast entity was configured in automatic mode. The Open-Meteo context that carries ET0, vapour-pressure deficit, and estimated radiation is now fetched independently of the precipitation-forecast source, so choosing a Home Assistant forecast no longer turns ET0 off.
- Fixed estimated radiation fallback being unavailable when the radiation source was forced to the STRÅNG API outside Nordic coverage. Estimated Open-Meteo radiation now also serves a forced API source that has no coverage, so light and the daily light integral no longer dead-end for that configuration.
- Fixed the per-series sample count cap silently undercutting the three-day time retention at fast update intervals. The cap is now sized from the retention window and the configured update interval, so a shorter interval no longer shrinks the buffer below the radiation lag and starves indoor-light pairing and complete-day light integrals.

### Changed

- Changed the outdoor-illuminance buffering to be removed entirely. It was written every cycle but read by nothing after indoor light moved to PAR pairing in 4.2.1.

### Testing

- Added provisional-light tests confirming that a calibrating indoor plant reports light, that a plant with too few observations does not fabricate a reading, and that outdoor plants are never flagged provisional.
- Expanded the automated suite accordingly.

## [4.2.1] - 2026-09-02

### Fixed

- Fixed indoor light never producing a value, with `light_score` and `source` remaining null even after a plant finished calibrating.
  - Root cause: the indoor window-transmission pairing read an outdoor-illuminance series that was populated separately from, and less reliably than, the photosynthetically active radiation (PAR) series.
  - Open-Meteo wrote outdoor illuminance under a source-suffixed key the reader never used, and STRÅNG derived it from a global-irradiance parameter that can be empty even when PAR is present.
  - PAR, the daily light integral, and daily light-hours continued to work, so the failure was silent: indoor light produced no observations and reported no state.

### Changed

- Changed indoor window-transmission pairing to use the reliable, source-correct PAR series populated by both STRÅNG and Open-Meteo. The window coefficient is a ratio, so only consistency of the outdoor reference between calibration and runtime is required; both now use PAR.
- Changed the dawn and dusk exclusion floor for window transmission from an illuminance value to a PAR value, aligned with the daylight threshold already used for light-hours.
- Changed locked baselines to record the light reference unit. A baseline calibrated before this change withholds its window coefficient instead of applying an illuminance-era coefficient to PAR pairing, so indoor light reports calibrating rather than a false obstruction or low-light state.

### Migration

- Existing indoor plants should be recalibrated once to establish a PAR-based window coefficient. Newly added plants calibrate correctly without any action.

### Testing

- Added indoor PAR-pairing tests confirming that indoor illuminance now pairs against the PAR series and produces window-transmission observations.
- Added light-reference migration-gate tests confirming that a pre-change baseline withholds its window coefficient while a new baseline applies it.
- Updated the window-transmission floor tests to PAR units.

### Known limitations

- The former outdoor-illuminance buffering is retained but no longer read by any consumer, pending removal in a later release.

## [4.2.0] - 2026-08-28

### Added

- Added persistent per-placement learning with independent indoor and outdoor baselines.
- Added a 14-day calibration lifecycle that extends automatically when observations are insufficient to establish a reliable baseline.
- Added learned constants for saturated soil-moisture peak, dry threshold, drying rate, outdoor daily light integral, indoor window transmission, normal soil temperature, and normal daily soil-temperature swing.
- Added conservative post-calibration adaptation of the learned saturated-moisture peak.
  - Adaptation runs once at the local-day boundary and never during calibration.
  - Only well-covered days with a genuine new peak are eligible.
  - The learned maximum can move only upward and remains bounded by an exponentially weighted moving average.
  - The dry threshold is regenerated from the stored standard or custom profile policy.
- Added complete placement-transition handling.
  - Indoor and outdoor baselines are preserved separately.
  - Returning to a calibrated placement immediately reuses its complete baseline.
  - Moving to an uncalibrated placement starts or resumes placement-specific calibration.
  - Local sample continuity and condition timers are cleared when placement changes.
- Added persistent condition timers for prolonged dry, wet, cold, and warm states.
- Added restart-safe storage for calibration progress, learned baselines, daily history, local samples, dormancy state, and condition timers.
- Added Open-Meteo as a keyless global outdoor-context provider for supported non-commercial use.
- Added selectable outdoor weather sources: automatic, configured Home Assistant forecast, Open-Meteo, and disabled.
- Added Open-Meteo context for air temperature, relative humidity, precipitation, precipitation probability, weather conditions, wind gusts, cloud cover, reference evapotranspiration, vapour-pressure deficit, shortwave radiation, diffuse radiation, modelled soil temperature, and regional modelled soil moisture.
- Added a bounded outdoor ET0 drying modifier.
  - A 24-hour ET0 value around 3 mm is neutral.
  - ET0 influence is bounded between 0.85 and 1.15.
  - The final combined environmental drying modifier is bounded between 0.60 and 1.15.
  - Indoor plants, stale context, missing values, and invalid values remain neutral.
  - The calibrated local drying rate remains authoritative and is never overwritten by forecast data.
- Added precipitation-probability-aware rain suppression.
  - When probability is available, forecast rain must meet both the configured amount threshold and a minimum probability of 60 percent.
  - Providers without probability retain amount-only behavior.
  - Invalid probability values cannot suppress watering guidance.
- Added estimated Open-Meteo radiation fallback outside Nordic STRÅNG coverage when automatic radiation selection is enabled.
- Added separate STRÅNG and Open-Meteo radiation histories so one provider cannot complete another provider's calendar day.
- Added diagnostics for learned and effective drying rate, ET0, precipitation forecast and probability, active radiation source, estimated status, fallback state, data age, and source-lock key.
- Added executable Home Assistant boundary tests using lightweight lifecycle fakes without adding a new test dependency.

### Changed

- Replaced the previous calculation paths with a provider-neutral v4 decision engine based on validated, timestamped, gap-aware samples.
- Changed daily learning to reduce raw samples into compact daily records rather than retaining unbounded history.
- Changed calibration to remain incomplete when required evidence is missing rather than creating a partially valid baseline.
- Changed outdoor moisture projections to combine the learned local drying rate with strictly bounded environmental pressure.
- Changed rain suppression to be recalculated and revocable on every coordinator update.
- Changed automatic radiation selection to use STRÅNG inside Nordic coverage and estimated Open-Meteo radiation elsewhere.
- Changed light calculations to use complete calendar days and source-isolated radiation histories.
- Changed Open-Meteo requests to use UTC and normalized returned timestamps to timezone-aware UTC before storage or calculation.
- Changed modelled Open-Meteo soil values to diagnostic regional context only. They never replace a physical plant sensor or calibrate a plant's local moisture baseline.
- Changed the Species entity to remain read-only context that cannot override learned plant-care decisions.
- Changed recalibration to clear only the active placement's learned baseline and local sample history while preserving the other placement's baseline and species context.
- Changed service calls to return actionable validation errors for missing or unknown plant IDs, an unloaded integration, missing species configuration, or a failed targeted refresh.
- Changed provider request accounting to report actual HTTP calls on successful, partial, and failed workflows.
- Changed provider diagnostics to expose sanitized failure summaries without remote response bodies.
- Changed public documentation to focus on installation, configuration, behavior, services, support, attribution, and release history.

### Fixed

- Fixed the manifest version not matching the advertised 4.2.0 release.
- Fixed placement changes being discarded instead of persisted.
- Fixed placement-transition decisions not affecting runtime behavior.
- Fixed target-placement calibration not being explicitly initialized or resumed.
- Fixed returning to a calibrated placement not having an authoritative reuse decision.
- Fixed cross-placement sample continuity and condition timers surviving placement changes.
- Fixed recalibration deleting both placement baselines.
- Fixed post-lock adaptation existing as an unused primitive rather than an active daily lifecycle operation.
- Fixed standard and custom dry thresholds drifting away from their persisted profile policy after peak adaptation.
- Fixed incomplete calibration appearing complete without all required evidence.
- Fixed invalid or missing telemetry contributing across gaps.
- Fixed partial days being returned by complete-day DLI and light-hour helpers.
- Fixed partial STRÅNG and Open-Meteo histories being eligible to form a false complete radiation day.
- Fixed naive and offset Open-Meteo timestamps being mixed with timezone-aware Home Assistant timestamps.
- Fixed rain suppression trusting low-confidence precipitation forecasts when probability data is available.
- Fixed invalid precipitation probabilities affecting watering suppression.
- Fixed radiation fallback being unavailable outside Nordic STRÅNG coverage.
- Fixed Open-Meteo context being requested separately for individual plants. One cached location-level request is now shared by all plants.
- Fixed stale Open-Meteo ET0 context being eligible to affect drying projections.
- Fixed unclear radiation diagnostics by identifying the active provider, estimated status, fallback state, data age, and source-lock key.
- Fixed the iNaturalist observation-photo fallback regressing to the overly restrictive `quality_grade=research` filter.
- Fixed provider error paths reporting optimistic or missing request counts.
- Fixed provider diagnostics exposing excerpts from remote response bodies.
- Fixed invalid service plant IDs being silently ignored.
- Fixed malformed or unreadable main plant storage preventing startup. Plant Helper now recovers with an empty in-memory store without immediately overwriting the unreadable payload.

### Security

- Kept optional provider credentials within Home Assistant configuration and storage paths.
- Added no hardcoded API keys, access tokens, plant identifiers, or private user information.
- Sanitized provider diagnostics so response bodies and credentials are not exposed in entity attributes or service results.
- Open-Meteo requires no API key for the supported non-commercial configuration.

### Documentation

- Rebuilt the README as the primary GitHub and HACS landing page.
- Added HACS custom-repository and manual installation instructions.
- Documented global settings, per-plant settings, entities, services, calibration, adaptation, persistence, removal, weather-source behavior, and Open-Meteo attribution.
- Removed internal roadmap, build-history, lifecycle-map, and repository-note links from the end-user README.
- Updated recalibration documentation to explain active-placement reset behavior.
- Updated automatic radiation-source wording to match the implemented STRÅNG and Open-Meteo policy.

### Testing

- Expanded the automated suite to 75 passing tests.
- Added exact version consistency checks across `manifest.json`, `CHANGELOG.md`, and the README release badge.
- Added Python syntax and import validation.
- Added ZIP integrity and release-package content verification.
- Added UTC timestamp and offset-conversion tests for Open-Meteo.
- Added strict complete-day DLI and light-hour regression tests.
- Added placement-specific recalibration and cross-provider radiation-isolation tests.
- Added provider photo-filter, call-count, sanitized-error, service-validation, and storage-recovery tests.
- Added executable lifecycle boundary tests for setup, store loading, initial refresh, platform forwarding, options reload, unload failure, successful shutdown, persistence saves, service execution, service cleanup, and invalid plant IDs.

### Known limitations

- Final verification in a running Home Assistant installation is still recommended for installation-specific entity behavior, recorder interaction, restart recovery, and external provider behavior. The automated suite exercises the integration lifecycle boundary with lightweight Home Assistant fakes but is not a substitute for a complete live installation test.
- Open-Meteo radiation is estimated from modelled shortwave radiation and must not be treated as measured PAR.
- Open-Meteo modelled soil moisture describes regional grid-cell conditions and does not represent moisture in an individual pot or planter.
- ET0 affects only the current outdoor drying projection and is not learned into the plant baseline.
- Vapour-pressure deficit remains diagnostic context to avoid double-counting environmental drying pressure.
- Post-lock adaptation currently applies only to the learned saturated-moisture peak and its derived dry threshold.
- Drying rate, daily light target, window transmission, thermal mean, and thermal swing remain locked after calibration until dedicated bounded adaptation policies are implemented.
- Open-Meteo use remains subject to its service terms, usage limits, and attribution requirements.

## [4.1.0] - 2026-08-22

### Added

- Added optional Open-Meteo plant environment context, configurable from Plant Helper global settings and disabled by default.
- Added regional model context for air temperature, relative humidity, precipitation, precipitation probability, reference evapotranspiration (ET0), vapour pressure deficit, shortwave radiation, wind speed, wind gusts, soil temperature at 6 cm, and soil moisture at 3-9 cm and 9-27 cm.
- Added a per-plant **Environment** diagnostic sensor that identifies values as `outdoor_model_context` for outdoor plants and `outside_context` for indoor plants.
- Added an Open-Meteo source module with unit preservation and one-hour successful-refresh throttling.
- Added focused tests for the selected Open-Meteo variable set and unit handling.

### Changed

- Extended the v4 engine result with an environmental-context field without changing the existing moisture, light, thermal, health, calibration, dormancy, or care-action calculations.
- Preserved configured physical plant sensors as the authoritative sources for soil moisture, soil temperature, illuminance, and battery state.
- Updated the setup and global-settings translations with the Open-Meteo option.
- Updated the README with the Open-Meteo context behavior, selected variables, and indoor/outdoor distinction.
- Bumped the integration version from `4.0.21` to `4.1.0`.

### Fixed

- Added the missing `get_linked_entity()` helper required by `plant_care_algorithms.py`, restoring relative-import validation and compatibility with current and legacy entity-key layouts.

### Known limitations

- Open-Meteo values are exposed as diagnostic context only and do not yet alter watering urgency, drying rate, rain suppression, health score, thermal state, light score, care actions, dormancy, or calibration.
- Optional Open-Meteo requests currently run in the main coordinator update path.
- Previously fetched Open-Meteo values are not yet marked as stale after a later request failure.
- Failed Open-Meteo requests can retry on each coordinator cycle until a successful refresh updates the throttle timestamp.
- Environment diagnostic entities are created even when Open-Meteo context is disabled.

## [3.2.0] - 2026-05-29

### Fixed

- Fixed watering alerts not clearing after a plant was watered.
  - `PlantBinaryBase` now listens for watered, fertilized, inspected, fetched, and added events.
  - Plant data is reloaded from storage after each event so sensorless plants update correctly.
  - Source-sensor updates and the binary sensor's `is_on` path also refresh state before evaluation.
- Fixed stale time-dependent metrics.
  - Both platforms now disable polling with `should_poll = False`.
  - Added a five-minute `async_track_time_interval` update that recomputes modelled moisture, days until watering, maintenance windows, and growth mode even when no linked sensor changes.
- Fixed a latent crash in `sensor.py`.
  - Two exception handlers referenced `_LOGGER` without defining it.
  - Entity-removal errors could therefore raise `NameError`.
  - `_LOGGER` is now defined correctly.

### API robustness

- Updated all three providers to use `response.json(content_type=None)` so unexpected HTML error responses do not cause JSON content-type failures.
- Changed API call counting to use the actual rate-limiter delta rather than optimistic increments.
- Updated the connectivity sensor to call `reset_if_needed()` before reading usage counters so post-midnight values remain accurate.
- Moved the iNaturalist `re` import to module scope.

### Maintainability and packaging

- Added `helpers.py` to centralize linked-entity resolution, legacy entity aliases, plant-name extraction, and scientific-name extraction.
- Removed duplicated helper logic that had drifted across five files.
- Changed `record_runtime_sample` to a synchronous function because it performed no asynchronous work.
- Added `services.yaml` documenting all nine services with selectors.
- Added `state_class = MEASUREMENT` to the four percentage sensors for long-term statistics.
- Limited database-summary attributes to 100 names to avoid exceeding Home Assistant state-size limits.
- Added `.editorconfig` and `.gitattributes` to preserve LF line endings.
- Converted `binary_sensor.py` from CRLF to LF line endings.

## [3.1.3] - 2026-05-27

### Fixed

- Fixed binary sensors showing null thresholds when provider data is incomplete.
  - Binary sensors now use the same default thresholds as the algorithm.
  - Default minimum soil moisture is 30%.
  - Default minimum temperature is 16 C.
  - Default maximum temperature is 29 C.
  - Default minimum illuminance is 1,200 lux.
- Fixed API rate limiting in the binary sensor to track Perenual, Trefle, and iNaturalist.
- Fixed the config-flow linked-sensor display showing `not set` for configured sensors.
- Fixed hardcoded API limits in the Trefle and iNaturalist providers.
- Fixed iNaturalist photos not appearing in sensor attributes.
- Fixed silent iNaturalist enrichment failures.
- Fixed cache hits bypassing iNaturalist enrichment.
- Fixed iNaturalist query handling for provider names containing group or cultivar suffixes.
- Removed the overly restrictive `quality_grade=research` filter while retaining the photo requirement.
- Fixed `add_user_plant` rejecting current linked-entity keys.
- Fixed the `needs_water` binary sensor not using the physics model.
- Fixed binary sensors creating a separate algorithm instance.
- Fixed binary-sensor source updates not recording runtime samples.
- Removed the unused `soil_moisture` field from every runtime sample.
- Consolidated duplicated plant-event constants into `const.py`.

### Changed

- Enhanced the API connectivity binary sensor with provider-specific diagnostic attributes.
- The API connectivity sensor now reports provider availability, rate-limit status, usage percentage, calls remaining, and next reset time.
- The connectivity sensor is on when at least one primary provider, Perenual or Trefle, is available.
- The `needs_water` binary sensor now exposes `calculated_soil_moisture`, `days_until_watering`, `watering_urgency`, `drying_rate_per_hour`, `soil_moisture_source`, and `days_since_watered`.
- Plant status sensors now always expose iNaturalist enrichment status and messages.
- iNaturalist observation links now use the scientific name for more accurate matching.

### Removed

- Removed unused `compact_dict()` from `api/base.py`.
- Removed unused `async_import_from_json()` from `storage.py`.
- Removed duplicated event constants from integration modules.
- Removed the duplicated `PERENUAL_DAILY_LIMIT` definition from `api/perenual.py`.

## [3.1.2] - 2026-05-24

### Changed

- Improved setup flow with clearer and more focused explanations.
- Removed repetitive API-key messages from non-setup pages.
- Enhanced menu descriptions to better explain each action.
- Added field-level help text for all form fields.
- Simplified verbose explanations across configuration pages.

### Fixed

- Fixed missing translations for the remove-plant, view-plants, and reset-database steps.
- Fixed description text not appearing on remove and reset pages.
- Fixed the options menu showing API setup information instead of action descriptions.

### Documentation

- Updated the README with a comprehensive feature list and examples.
- Added troubleshooting information.
- Improved the quick-start guide.
- Added automation examples.

## [3.1.1] - 2026-05-24

### Added

- Added calculated soil moisture without requiring a physical moisture sensor.
- Added evaporation modelling based on environmental conditions.
- Added a health score sensor with a weighted score from 0 to 100.
- Added a care-action sensor with specific recommendations.

### Changed

- Improved API rate limiting with per-provider controls.
- Enhanced provider error handling.
- Added more detailed sensor attributes.

### Fixed

- Fixed sensor states not updating immediately.
- Fixed timestamp parsing for watering events.
- Fixed an edge case in calculated soil moisture.

## [3.1.0] - 2026-05-24

### Added

- Added optional iNaturalist enrichment without requiring an API key.
- Added Trefle as a fallback provider.
- Added daily light-score tracking.
- Added a temperature stress-load sensor.
- Added an API-status binary sensor.

### Changed

- Migrated providers to an asynchronous architecture.
- Improved local provider caching.
- Improved config-flow validation.
- Moved provider modules into the `api/` package.

### Fixed

- Fixed a race condition during storage initialization.
- Fixed timezone handling for sensor timestamps.
- Fixed species-key extraction from varied provider responses.

## [3.0.0] - 2026-05-24

### Added

- Initial release with a local-first architecture.
- Added Perenual as the primary plant-data provider.
- Added a local SQLite plant database.
- Added UI-based configuration.
- Added a plant-status sensor with grouped attributes.
- Added services for plant and database management.
- Added per-provider API rate limiting.

### Features

- Search for plants by common name.
- Add configured plants with custom names.
- Link existing Home Assistant temperature, humidity, and light sensors.
- Fetch plant data without creating entities.
- View configured and cached plants.
- Reset the local database.

---

## Legend

- `Added` for new features
- `Changed` for changes to existing functionality
- `Deprecated` for features scheduled for removal
- `Removed` for removed features
- `Fixed` for bug fixes
- `Security` for security improvements
- `Documentation` for documentation changes
- `Testing` for test-suite and verification improvements
