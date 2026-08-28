# Changelog

All notable changes to Plant Helper will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [4.2.0] - 2026-08-28

### Added

- Added a persistent per-placement learning system with independent indoor and outdoor baselines.
- Added a 14-day initial calibration lifecycle that automatically extends when the available observations are insufficient to create a reliable baseline.
- Added learned plant constants for:
  - saturated soil-moisture peak
  - dry threshold
  - drying rate
  - outdoor daily light integral target
  - indoor window-transmission factors
  - normal soil-temperature mean
  - normal daily soil-temperature swing
- Added conservative post-calibration adaptation of the learned saturated-moisture peak.
  - Adaptation only occurs from a well-covered day.
  - The candidate must be a genuine new moisture peak.
  - The learned maximum can only move upward.
  - Changes are bounded by an exponentially weighted moving average.
  - Adaptation runs once at the local-day boundary and never during calibration.
- Added profile-aware dry-threshold regeneration after moisture-peak adaptation.
  - Standard profiles use their stored profile multiplier.
  - Custom profiles use their persisted custom multiplier.
  - Legacy baselines without policy metadata use a ratio-preserving migration fallback.
- Added complete placement-transition handling.
  - Placement changes now persist correctly.
  - Indoor and outdoor baselines are preserved separately.
  - Returning to a calibrated placement immediately reuses its complete baseline.
  - Changing to an uncalibrated placement starts or resumes placement-specific calibration.
  - Local sample continuity and condition timers are cleared when placement changes.
- Added persistent condition timers for prolonged dry, wet, cold, and warm states.
- Added restart-safe storage for calibration progress, learned baselines, daily history, local samples, dormancy state, and condition timers.
- Added a twelve-stage learning lifecycle map documenting state ownership, behavioral coverage, structural contracts, and remaining live Home Assistant verification.
- Added HACS custom-repository metadata and repository documentation.
- Added a quality roadmap that tracks completed functionality and remaining verification work.
- Added an Open-Meteo global outdoor-context provider with no API key required for supported non-commercial use.
- Added selectable outdoor weather sources:
  - automatic
  - configured Home Assistant forecast
  - Open-Meteo
  - disabled
- Added Open-Meteo context for:
  - air temperature
  - relative humidity
  - precipitation
  - precipitation probability
  - weather conditions
  - wind gusts
  - cloud cover
  - reference evapotranspiration
  - vapour pressure deficit
  - shortwave radiation
  - diffuse radiation
  - modelled soil temperature
  - regional modelled soil moisture
- Added a bounded outdoor reference-evapotranspiration drying modifier.
  - A 24-hour ET0 value around 3 mm is neutral.
  - ET0 influence is bounded between 0.85 and 1.15.
  - The final combined environmental drying modifier is bounded between 0.60 and 1.15.
  - Indoor plants, stale context, missing values, and invalid values remain neutral.
  - The calibrated local drying rate remains authoritative and is never overwritten by forecast data.
- Added precipitation-probability-aware rain suppression.
  - When probability is available, forecast rain must meet both the configured amount threshold and a minimum probability of 60%.
  - Low-confidence rain no longer suppresses watering guidance.
  - Forecast providers without probability retain the established amount-only behavior.
  - Invalid precipitation probabilities cannot suppress watering guidance.
- Added an estimated Open-Meteo radiation fallback for locations outside Nordic STRANG coverage.
  - The fallback is used only when the radiation source is set to automatic.
  - Explicit STRANG API and Home Assistant sensor modes remain authoritative.
  - Open-Meteo shortwave radiation is converted into clearly identified estimated PAR and outdoor illuminance histories.
  - Open-Meteo and STRANG radiation samples use separate storage keys.
  - Complete daily light calculations cannot mix radiation providers within one calendar day.
- Added diagnostic attributes for:
  - learned drying rate
  - effective drying rate
  - ET0 for the next 24 hours
  - ET0 drying modifier
  - forecast precipitation for the next 48 hours
  - maximum precipitation probability for the next 48 hours
  - active radiation source
  - whether radiation is estimated
  - active radiation source-lock key
- Added behavioral tests for calibration, incomplete-calibration extension, baseline locking, post-lock adaptation, placement transitions, threshold regeneration, ET0 behavior, precipitation probability, Open-Meteo parsing, radiation conversion, and source isolation.

### Changed

- Replaced the previous loosely connected calculation paths with a provider-neutral v4 decision engine.
- Changed moisture guidance to use validated, timestamped, gap-aware sample series.
- Changed daily learning to reduce raw samples into compact daily records rather than retaining unbounded raw history.
- Changed calibration status to remain incomplete when required evidence is missing instead of creating a partially valid baseline.
- Changed outdoor moisture projections to use the learned local drying rate combined with strictly bounded environmental pressure.
- Changed rain suppression to remain revocable on every coordinator update.
- Changed radiation-source selection so automatic mode prefers STRANG inside Nordic coverage and uses estimated Open-Meteo radiation elsewhere.
- Changed light calculations to use complete calendar days and source-isolated radiation histories.
- Changed provider data to remain advisory or environmental context unless a specific, bounded policy explicitly connects it to the decision engine.
- Changed modelled Open-Meteo soil values to diagnostic regional context only.
  - They never replace a physical plant sensor.
  - They are never used to calibrate a plant's local moisture baseline.
- Changed the Species entity to remain read-only context that cannot override learned plant-care decisions.
- Changed service behavior so recalibration clears the selected plant's learned model and samples while preserving unrelated species context.
- Changed repository documentation to clearly separate automated behavioral tests, repository-level Home Assistant contracts, and pending live verification.
- Changed repository packaging to support installation as a HACS custom repository.
- Changed the public project language to describe tested capabilities and verification status without claiming an externally awarded quality designation.

### Fixed

- Fixed placement changes being silently discarded instead of being persisted.
- Fixed placement-transition code being called without its result affecting runtime behavior.
- Fixed target-placement calibration not being explicitly initialized or resumed.
- Fixed returning to a previously calibrated placement not having an authoritative reuse decision.
- Fixed cross-placement sample continuity and condition timers surviving placement changes.
- Fixed post-lock adaptation being implemented as an unused primitive rather than an active daily lifecycle operation.
- Fixed adapted dry thresholds being rescaled by the previous ratio for all plants.
  - Standard and custom profiles now regenerate the threshold from their persisted policy.
- Fixed custom-profile dry thresholds being able to drift away from their configured custom multiplier.
- Fixed incomplete calibration being able to appear complete without all required evidence.
- Fixed invalid or missing telemetry being able to contribute across gaps.
- Fixed rain suppression trusting low-confidence precipitation forecasts when probability data is available.
- Fixed invalid precipitation-probability values being eligible to affect watering suppression.
- Fixed radiation fallback being limited to Nordic STRANG coverage.
- Fixed the possibility of mixing STRANG and estimated Open-Meteo radiation samples in one daily light calculation.
- Fixed Open-Meteo context being requested separately for individual plants.
  - One cached location-level request is now shared by all plants.
- Fixed stale Open-Meteo ET0 context being eligible to affect drying projections.
- Fixed unclear radiation diagnostics by identifying the active provider, estimated status, fallback status, data age, and source-lock key.
- Fixed repository documentation and release metadata being incomplete for HACS custom-repository use.

### Security

- Kept all optional provider credentials within the Home Assistant configuration flow and storage paths.
- Added no hardcoded API keys, access tokens, plant identifiers, or private user information.
- Open-Meteo requires no API key for the supported non-commercial configuration.
- Provider failures are handled without exposing response bodies or credentials in normal diagnostic output.

### Documentation

- Rebuilt the README as the primary GitHub and HACS landing page.
- Added HACS custom-repository installation instructions.
- Added manual installation and removal instructions.
- Documented global settings, per-plant settings, entities, services, calibration, adaptation, persistence, and weather-source behavior.
- Added `docs/QUALITY_ROADMAP.md`.
- Added `docs/LEARNING_LIFECYCLE.md`.
- Added `docs/HACS.md`.
- Added Open-Meteo attribution and clarified that modelled soil values are regional context only.
- Documented the six live Home Assistant lifecycle checks required before the release is described as field-verified.

### Testing

- Expanded the automated suite to 61 passing tests.
- Added complete Python syntax validation.
- Added relative-import and symbol validation.
- Added ZIP integrity verification for release packages.
- Added regression coverage for the existing provider, storage, entity, lifecycle, timer, calibration, and STRANG behavior.
- Added focused Open-Meteo tests for parsing, units, weather-code normalization, ET0, precipitation probability, shortwave-to-PAR conversion, complete-day DLI, coverage selection, explicit source modes, and source isolation.

### Known limitations

- Final verification in a running Home Assistant instance is still required for setup, options changes, entity behavior, service behavior, placement transitions, restart recovery, unload, and reload.
- Open-Meteo radiation is estimated from modelled shortwave radiation and must not be treated as measured PAR.
- Open-Meteo modelled soil moisture describes regional grid-cell conditions and does not represent moisture in an individual pot or planter.
- ET0 affects only the current outdoor drying projection and is not learned into the plant baseline.
- Vapour pressure deficit remains diagnostic context to avoid double-counting environmental drying pressure.
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
