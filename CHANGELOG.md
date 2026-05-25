# Changelog

All notable changes to Plant Helper will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.1.3] - 2026-05-25

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

### Changed
- Enhanced API connectivity binary sensor with per-provider detailed attributes
  - Shows which APIs are available, at limit, or have errors
  - Displays usage statistics and next reset time for each provider
  - Binary sensor now ON if ANY primary provider (Perenual OR Trefle) is available

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

## [3.1.1] - 026-05-24

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

## [3.1.0] - 026-05-24

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

## [3.0.0] - 026-05-24

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
