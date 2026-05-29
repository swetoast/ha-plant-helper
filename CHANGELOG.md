# Changelog

All notable changes to Plant Helper will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.2.0] - 2026-05-29

### Bug fixes

- Watering alerts now clear (the headline bug). PlantBinaryBase now listens to watered/fertilized/inspected/fetched/added events and reloads plant_data from storage on each, so sensorless plants update correctly. Source-sensor updates and the binary sensor's is_on path also refresh state first.
- Stale time-dependent metrics. Both platforms now disable polling (should_poll = False) and add a 5-minute async_track_time_interval that recomputes modeled moisture, days-until-watering, maintenance windows, and growth mode even when no linked sensor ticks.
 -Found and fixed a latent crash I'd missed in the audit: sensor.py referenced _LOGGER in two except blocks but never defined it — any entity-removal error would have raised NameError. Now defined. (Pre-existing in your upload.)

### API robustness

- All three providers use response.json(content_type=None) so HTML error pages don't throw.
- calls_made now counted via a real limiter delta instead of optimistic += 1, so usage counters match reality.
- Connectivity sensor calls reset_if_needed() before reading counts, so post-midnight numbers are correct.
- re import in iNaturalist hoisted to module top.

### Maintainability & packaging

- New helpers.py centralizes the linked-entity resolver + alias map + name extractors that were duplicated (and had drifted) across five files.
- record_runtime_sample made synchronous (it never awaited) and called directly.
- New services.yaml documenting all 9 services with selectors.
- state_class = MEASUREMENT on the four % sensors for long-term statistics.
- Database summary attributes capped at 100 names to stay under HA's state-size limit.
- .editorconfig + .gitattributes to keep line endings LF; binary_sensor.py converted from CRLF.

## [3.1.3] - 2026-05-27

### Fixed
- **CRITICAL:** Fixed binary sensors showing null thresholds when provider data is incomplete
  - Binary sensors now use default thresholds matching the algorithm behavior
  - Defaults: soil_moisture_min=30, temperature_min=16, temperature_max=29, lux_min=1200
  - Fixes issue where plants with missing Perenual watering data had non-functional binary sensors
- Fixed API rate limiting in binary sensor to track all three providers (Perenual, Trefle, iNaturalist)
  - Binary sensor now shows comprehensive status for all APIs
  - Added availability status, usage percentages, and calls remaining for each provider
- Fixed config flow linked sensors display showing "not set" for all sensors
  - Corrected entity key mapping to use actual storage keys instead of configuration constants
- Fixed hardcoded API limits in Trefle and iNaturalist providers
  - Now properly use TREFLE_DAILY_LIMIT and INATURALIST_DAILY_LIMIT constants
- **iNaturalist photos not appearing in sensor attributes**
  - Fixed photo URL transformation: iNaturalist only returns `url` (square thumbnail); code
    was looking for non-existent `large_url`/`medium_url` fields. Now correctly rewrites
    `square.jpg` → `large.jpg` in the URL path
  - Fixed silent enrichment failure: when enrichment failed for any reason (rate limit,
    API error, disabled) the `inat` key was silently omitted with no diagnostic info.
    Enrichment status, message, and error details are now always written to plant data
    and surfaced as sensor attributes (`inaturalist_enriched`, `inaturalist_message`,
    `inat_error`)
  - Fixed cache bypass: plants served from local cache skipped enrichment entirely.
    Cache hits now run iNaturalist enrichment before returning
  - Fixed query cleaning: provider names like `"Spathiphyllum (group)"` and cultivar
    suffixes like `'Neon'` are stripped before querying iNaturalist, which does not
    recognise these suffixes as valid taxon names
  - Removed overly strict `quality_grade=research` filter that blocked the majority of
    iNaturalist observations; photos filter (`photos=true`) is retained
- **`add_user_plant` service rejecting new entity keys**
  - `SCHEMA_ADD_USER_PLANT` only accepted old-style keys (`humidity_entity`,
    `temperature_entity`, etc.). Voluptuous rejected calls using new keys introduced by
    the config flow (`room_temperature`, `room_humidity`, `room_lux`, `soil_moisture`,
    `soil_temperature`). Schema now accepts all key styles
- **`needs_water` binary sensor not using physics model**
  - Sensor was a simple raw-sensor threshold check; if no physical moisture sensor was
    linked it returned `off` permanently. Now uses the same `PlantCareAlgorithms`
    physics model as `calculated_soil_moisture`, with three trigger conditions:
    calculated moisture below minimum, less than 1 day until watering needed, or
    watering urgency score ≥ 70. Falls back to threshold check if algorithms unavailable
  - Fixed separate `PlantCareAlgorithms` instance being created in binary sensor setup:
    binary sensors now reuse the shared instance stored in `runtime_data["algorithms"]`
    by the sensor platform, ensuring both platforms share the same sample history
  - Fixed `_handle_sensor_update` not calling `record_runtime_sample`: binary sensors
    now record a runtime sample whenever a linked entity updates, matching sensor
    platform behaviour and keeping growth-mode and drying-rate calculations accurate
- **Dead `"soil_moisture"` key stored in every runtime sample**
  - `record_runtime_sample` stored a `soil_moisture` key that no calculation ever read
    (moisture is read from live HA state via `_current_environment`, not from the sample
    buffer). Removed to reduce per-sample memory overhead
- **Duplicate event constant definitions across four files**
  - `EVENT_PLANT_*` strings were independently redefined in `__init__.py`, `sensor.py`,
    `binary_sensor.py`, and `config_flow.py`. A divergence would have silently broken
    event routing. All event constants are now defined once in `const.py` and imported
    everywhere else

### Changed
- Enhanced API connectivity binary sensor with per-provider detailed attributes
  - Shows which APIs are available, at limit, or have errors
  - Displays usage statistics and next reset time for each provider
  - Binary sensor now ON if ANY primary provider (Perenual OR Trefle) is available
- `needs_water` binary sensor attributes now expose physics model metrics:
  `calculated_soil_moisture`, `days_until_watering`, `watering_urgency`,
  `drying_rate_per_hour`, `soil_moisture_source`, `days_since_watered`
- `sensor.peace_lily_plant_status` (and all plant status sensors) now always expose
  `inaturalist_enriched` and `inaturalist_message` attributes for diagnostics, even
  when enrichment fails or is disabled
- iNaturalist observation URL in sensor attributes now uses `scientific_name` instead
  of the species key for more accurate taxon matching

### Removed
- Removed 26 lines of dead code across integration
  - Removed unused `compact_dict()` function from api/base.py
  - Removed unused `async_import_from_json()` method from storage.py
  - Removed duplicate event constants from const.py (kept API daily limit constants only)
  - Removed duplicate PERENUAL_DAILY_LIMIT from api/perenual.py (now imports from const.py)

## [3.1.2] - 2026-05-24

### Changed
- Improved setup flow with clearer, more focused explanations
- Removed repetitive API key messages from non-setup pages
- Enhanced menu descriptions to better explain each action
- Added field-level help text (`data_description`) for all form fields
- Simplified verbose explanations across all configuration pages

### Fixed
- Fixed missing translations for remove_plant, view_plants, and reset_database steps
- Fixed description text not appearing on remove and reset pages
- Corrected options menu showing API setup info instead of action descriptions

### Documentation
- Updated README with comprehensive feature list and examples
- Added troubleshooting section
- Improved quick start guide
- Added automation examples

## [3.1.1] - 2026-05-24

### Added
- Support for calculated soil moisture without physical sensor
- Smart evaporation modeling based on environmental conditions
- Health score sensor (0-100 weighted overall wellness)
- Care action sensor with specific recommendations

### Changed
- Improved API rate limiting with per-provider controls
- Enhanced error handling for provider connectivity issues
- Updated sensor attributes with more detailed information

### Fixed
- Fixed issue with sensor state updates not triggering immediately
- Corrected timestamp parsing for last watering events
- Fixed edge case in soil moisture calculation

## [3.1.0] - 2026-05-24

### Added
- iNaturalist enrichment support (optional, no API key required)
- Trefle fallback provider for plants not in Perenual
- Light score tracking (daily lux accumulation)
- Temperature stress load sensor
- API status binary sensor for diagnostics

### Changed
- Migrated to async provider architecture
- Improved local caching strategy
- Enhanced config flow with better validation
- Reorganized provider modules into api/ subdirectory

### Fixed
- Fixed race condition in storage initialization
- Corrected timezone handling for sensor timestamps
- Fixed issue with species key extraction from varied data formats

## [3.0.0] - 2026-05-24

### Added
- Initial release with local-first architecture
- Perenual integration as primary data provider
- Local plant database with SQLite storage
- Config flow for UI-based setup
- Plant status sensor with grouped attributes
- Services for plant and database management
- Rate limiting for API calls

### Features
- Search plants by common name
- Add configured plants with custom names
- Link existing Home Assistant sensors (temperature, humidity, light)
- Fetch plant data without creating sensors
- View configured and cached plants
- Reset database functionality

---

## Legend

- `Added` - New features
- `Changed` - Changes in existing functionality
- `Deprecated` - Soon-to-be removed features
- `Removed` - Removed features
- `Fixed` - Bug fixes
- `Security` - Security improvements
- `Documentation` - Documentation updates
