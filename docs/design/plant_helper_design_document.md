# Plant Helper Complete Design Plan

**Status:** Design specification  
**Target platform:** Home Assistant 2025.12.2  
**Document date:** 2026-09-22  

## 1. Purpose

Plant Helper is a Home Assistant custom integration that converts physical plant-sensor observations into calibrated, time-aware, placement-aware plant-care information.

Plant Helper combines:

1. Physical plant sensors
2. Independent indoor and outdoor learned baselines
3. Placement-specific behavior
4. Shared Open-Meteo environmental context
5. Cached species enrichment from Perenual, Trefle, and iNaturalist
6. Conservative fallback behavior

The authority order is:

```text
Physical sensor readings
↓
Learned local plant behavior
↓
Placement-specific rules
↓
Open-Meteo environmental context
↓
Cached species context
↓
Conservative defaults
```

External information never replaces valid physical telemetry or learned local behavior.

## 2. Home Assistant architecture

### 2.1 Integration identity

Plant Helper uses one configuration entry representing one hub.

```text
Domain: plant_helper
Unique ID: plant_helper
Entry title: Plant Helper
Maximum entries: 1
```

A second setup attempt aborts with `single_instance_allowed`.

### 2.2 Platforms

Plant Helper provides:

```text
sensor
binary_sensor
```

The public entity contract must remain stable once implemented:

- Entity IDs
- Unique IDs
- State types
- Units
- Device classes
- State classes
- Availability behavior
- Core attribute structure

Configuration changes must not create duplicate entities or devices.

### 2.3 Device structure

The integration exposes:

```text
Plant Helper hub device
Individual plant devices
```

The hub contains only meaningful integration-level entities. Each configured plant has one device containing that plant's care, health, moisture, light, temperature, calibration, species, and selected diagnostic entities.

Provider-specific entity proliferation is prohibited.

## 3. Configuration ownership

### 3.1 Config-entry data

`ConfigEntry.data` contains stable integration identity only.

```python
data = {}
```

Global settings, plants, learned state, and samples do not belong in `ConfigEntry.data`.

### 3.2 Config-entry options

`ConfigEntry.options` contains global settings:

```text
latitude
longitude
perenual_api_key
perenual_access_level
trefle_api_key
update_interval
```

No revision nonce or artificial change counter is stored.

### 3.3 Plant configuration storage

Plant configuration belongs to the dedicated Plant Helper storage layer.

```text
plant_uuid
display_name
species
created_at
updated_at
configuration:
  soil_moisture
  soil_temperature
  humidity_sensor
  lux
  battery
  placement
  profile
  custom_multiplier
  rain_limit_mm
```

Plant configuration remains separate from:

- Learned baselines
- Calibration progress
- Active rolling samples
- Timers
- Historical observations
- Species enrichment
- Coordinator state

## 4. Initial setup flow

### 4.1 Setup form

Initial setup presents the complete global settings form:

- Latitude override
- Longitude override
- Ozone sensor
- Perenual API key
- Perenual access level
- Trefle API token
- Update interval

The setup and reconfigure flows use the same schema, selectors, defaults, normalization, and validation rules.

### 4.2 Setup sequence

```text
Start setup
↓
Check for existing Plant Helper entry
↓
Build global settings schema
↓
Apply safe defaults
↓
Display form
↓
Validate submission
↓
Normalize values
↓
Create one config entry
↓
Set up integration
```

### 4.3 Setup result

Optional values that were not supplied are omitted. Minimum stored options:

```python
{
    "perenual_access_level": "free",
    "update_interval": 300,
}
```

### 4.4 Setup failure behavior

Expected failures return translated form errors. Unexpected failures are logged with technical context, do not expose credentials, return a translated base error, keep the form usable, and never become an empty frontend error dialog.

## 5. Global reconfiguration

Global settings use a proper reconfigure flow.

### 5.1 Reconfigure sequence

```text
Start reconfigure
↓
Load current config entry
↓
Normalize current settings
↓
Build the shared global settings schema
↓
Add current values as suggested values
↓
Display form
↓
Validate submission
↓
Normalize submitted values
↓
Replace complete global settings set
↓
Update existing config entry
↓
Reload integration exactly once
↓
Complete flow
```

### 5.2 Clear semantics

Clearing an optional field removes its stored value:

```text
latitude
longitude
perenual_api_key
trefle_api_key
```

Cleared values remain absent after config-entry update, integration reload, Home Assistant restart, and reopening reconfigure.

### 5.3 Reconfigure guarantees

Successful reconfiguration preserves:

- Config-entry ID
- Plant UUIDs
- Plant configuration
- Device identifiers
- Entity unique IDs
- Entity IDs
- Learned baselines
- Calibration state
- Samples
- Timers

Invalid submission performs no update and no reload.

## 6. Global settings contract

### 6.1 Latitude

```text
Type: float
Required: no
Minimum: -90
Maximum: 90
Fallback: Home Assistant latitude
```

The value must be finite. Boolean input is invalid. Numeric strings may normalize to floats. Clearing removes the override.

### 6.2 Longitude

```text
Type: float
Required: no
Minimum: -180
Maximum: 180
Fallback: Home Assistant longitude
```

The latitude numeric rules also apply to longitude.

### 6.3 Ozone entity

```text
Type: entity ID
Required: no
Allowed domain: sensor
```

The selected entity can be temporarily unavailable. Clearing disables configured physical-ozone behavior. Ozone is relevant only to outdoor plants.

### 6.4 Perenual API key

```text
Type: string
Required: no
Selector: password
```

Rules:

- Trim surrounding whitespace
- Preserve remaining content
- Empty input removes the key
- Never expose the key in diagnostics, state, logs, exceptions, or retained URLs

### 6.5 Perenual access level

```text
Type: string
Required: yes
Default: free
Allowed values:
  free
  paid
```

No other value reaches runtime behavior.

### 6.6 Trefle API token

```text
Type: string
Required: no
Selector: password
```

The same secret-handling rules used for Perenual apply.

### 6.7 Update interval

```text
Type: integer
Required: yes
Minimum: 60 seconds
Maximum: 3600 seconds
Default: 300 seconds
Step: 30 seconds
```

This interval controls periodic Plant Helper processing, not external species-provider refresh frequency.

## 7. Plant-management options flow

The options menu contains only:

```text
Add a plant
Edit a plant
Remove a plant
```

Global settings are not part of the plant-management menu.

### 7.1 Flow-local state

Each options-flow instance may hold temporary in-memory state:

```text
selected_plant_uuid
pending_form_input
expected_storage_revision
current_step
```

This state is discarded when the flow is cancelled or closed. Persistent storage is not mutated until final validated submission.

### 7.2 No early mutation

The following actions never mutate persistent storage:

- Opening the options menu
- Opening Add plant
- Selecting a plant to edit
- Opening Edit plant
- Selecting a plant to remove
- Navigating back
- Closing the dialog
- Cancelling the flow
- Validation failure

## 7.3 Storage revision and optimistic locking

`PlantHelperStorage` implements optimistic concurrency because Home Assistant storage does not provide record-level optimistic locking for this workflow.

The stored JSON payload contains a top-level monotonic integer:

```json
{
  "schema_version": 1,
  "version": 42,
  "plants": {},
  "species_cache": {},
  "metadata": {}
}
```

Rules:

- `version` begins at `0` for a new store.
- Every successful persistent mutation increments `version` exactly once.
- Reads return both the requested data and the version observed.
- Multi-step Add, Edit, and Remove flows retain `expected_storage_revision` in flow-local memory.
- Before commit, the flow re-reads the store and requires `current_version == expected_storage_revision`.
- A mismatch returns `plant_changed` or `storage_changed` without writing.
- Failed writes do not increment the version.
- Background species-cache writes also increment the version, so plant mutations must use a storage transaction method that revalidates only the affected plant record as well as the top-level version.

To prevent unrelated background enrichment from causing needless plant-edit conflicts, `PlantHelperStorage` also stores a per-plant revision:

```json
{
  "plant_uuid": "4ea2d38090b04ecfa91d97801e41c28a",
  "revision": 7,
  "display_name": "Snake Plant",
  "configuration": {}
}
```

Commit rules:

```text
Edit plant
→ require current plant revision == expected plant revision
→ write replacement
→ increment plant revision
→ increment top-level storage version

Remove plant
→ require plant exists
→ require current plant revision == expected plant revision
→ remove record
→ increment top-level storage version

Add plant
→ require UUID absent
→ add revision 1 record
→ increment top-level storage version
```

The top-level version protects complete-store consistency. The per-plant revision prevents stale edits while allowing unrelated species-cache and other-plant changes to proceed safely.

All storage mutations execute under one integration-owned `asyncio.Lock` so the compare-and-write sequence is atomic within the Home Assistant process.

## 8. Plant configuration contract

### 8.1 Required fields

```text
display_name
soil_moisture
placement
profile
rain_limit_mm
```

`rain_limit_mm` is stored for every plant but used only when placement is outdoor.

### 8.2 Optional fields

```text
species
soil_temperature
humidity_sensor
lux
battery
custom_multiplier
```

`custom_multiplier` is required only when the custom care profile is selected.

### 8.3 Physical sensor selectors

#### Soil moisture

```text
Domain: sensor
Device classes:
  moisture
  humidity
Required: yes
```

The humidity device class is accepted because some soil-moisture devices expose moisture using that class.

#### Soil temperature

```text
Domain: sensor
Device class: temperature
Required: no
```

#### Air humidity

```text
Domain: sensor
Device class: humidity
Required: no
```

This is a distinct air-humidity source, not the soil-moisture sensor.

#### Light

```text
Domain: sensor
Device class: illuminance
Required: no
```

#### Battery

```text
Domain: sensor
Required: no
```

Battery sources may report numeric or categorical states.

## 9. Plant identity

### 9.1 Immutable UUID

Every new plant uses:

```python
uuid.uuid4().hex
```

Name slugification is used only for the initial default entity object ID, never as internal identity.

### 9.2 Identity mapping

```text
Plant device identifier:
  (plant_helper, <plant_uuid>)

Plant entity unique ID:
  <entry_id>_<plant_uuid>_<entity_key>
```

Renaming a plant does not change the UUID, unique IDs, entity IDs, or device identifier.

### 9.3 Duplicate names

Duplicate display names are allowed. Selectors distinguish duplicates with useful context while retaining UUID as the selector value.

Example labels:

```text
Snake Plant · Living room
Snake Plant · Bedroom
```

## 10. Physical sensor rules

### 10.1 Authority

Physical sensors are authoritative for current plant conditions. Plant Helper never fabricates replacements for missing physical readings.

```text
Missing soil moisture
→ normal moisture-based care cannot be produced

Missing indoor light sensor
→ no_light_sensor

Missing optional soil temperature
→ no physical temperature compensation

Missing optional air humidity
→ no physical dry-air evaluation

Missing battery
→ no battery context
```

### 10.2 State classification

```text
valid
unknown
unavailable
invalid
out_of_range
```

Temporary unavailability does not erase configuration.

### 10.3 Moisture validation

Valid moisture range:

```text
0–100 percent
```

A valid 0 reading is retained and treated as dry, not as missing. Invalid readings do not enter learning or care calculations.

## 11. Add plant flow

```text
Display Add plant form
↓
Validate required fields
↓
Inspect current moisture state when available
↓
Validate profile-specific values
↓
Normalize complete plant configuration
↓
Allocate immutable UUID
↓
Persist plant atomically
↓
Verify storage success
↓
Add runtime plant dynamically
↓
Register physical-sensor listeners
↓
Add plant entities dynamically
↓
Schedule species enrichment if needed
↓
Run immediate local evaluation
↓
Complete flow
```

External-provider failure does not prevent plant creation.

If validation or persistence fails, the form remains open, submitted values remain populated, a translated error is displayed, no partial plant is reported as added, and no global reload occurs.

## 12. Edit plant flow

### 12.1 Selection

Selector value is `plant_uuid`; label is the user-facing plant name plus context.

No plants:

```text
Abort: no_plants
```

Missing selected plant:

```text
Abort: plant_not_found
```

### 12.2 Replacement behavior

Editing replaces the complete editable field set. Clearing an optional field removes the previous value.

This applies to:

- Species
- Soil temperature
- Air humidity
- Light
- Battery
- Custom multiplier

Unknown internal fields are preserved.

### 12.3 Transaction

```text
Select plant
↓
Copy current configuration into flow-local memory
↓
Display complete edit form
↓
Validate submitted replacement
↓
Re-read current stored plant
↓
Check storage revision
↓
Persist replacement atomically
↓
Update runtime object
↓
Rebuild changed sensor listeners
↓
Apply placement transition if needed
↓
Schedule enrichment if species changed
↓
Evaluate current state
↓
Complete flow
```

If the plant changed while the flow was open, the stale flow does not overwrite the newer record.

## 13. Remove plant flow

Removal requires an explicit confirmation step.

### 13.1 Transaction boundary

```text
Select plant
↓
Display plant name and irreversible cleanup summary
↓
User confirms
↓
Re-read plant and verify expected plant revision
↓
Remove stored configuration atomically
↓
Verify persistence
↓
Begin runtime and registry cleanup
```

If stored configuration removal fails, none of the runtime, learned-data, entity, or registry cleanup occurs.

### 13.2 Dynamic cleanup order

After persistent removal succeeds, cleanup occurs in this exact order:

1. Cancel the plant's pending debounce and evaluation tasks.
2. Unsubscribe every configured physical state-change listener.
3. Prevent new coordinator evaluations by marking the runtime plant as removing.
4. Remove the plant from coordinator indexes and reverse entity-to-plant mappings.
5. For every loaded plant entity, call `await entity.async_remove()` so the entity lifecycle runs and the state-machine entry is removed.
6. Obtain the Entity Registry with `er.async_get(hass)` and call `entity_registry.async_remove(entity_id)` for every entity owned by the plant UUID.
7. Verify no remaining entity-registry entry for the config entry uses the plant UUID unique-ID prefix.
8. Obtain the Device Registry with `dr.async_get(hass)` and remove the plant device only after all child entities are gone.
9. Remove learned placement baselines, active rolling samples, timers, and plant-specific history.
10. Notify dynamic platforms that the UUID is no longer present.

The entity object's `async_will_remove_from_hass()` lifecycle is responsible for entity-owned subscriptions. Integration-level physical listeners are cancelled separately before entity removal.

Registry matching must use the config-entry ID and immutable plant UUID. Display names and entity IDs are never used as ownership boundaries.

### 13.3 Partial cleanup failure

Persistent configuration removal is authoritative. If a later cleanup step unexpectedly fails:

- Continue best-effort cleanup of remaining independent resources.
- Record a redacted cleanup diagnostic.
- Schedule an idempotent cleanup retry.
- Do not recreate the plant configuration.
- Do not remove resources belonging to another plant.

All cleanup operations must be idempotent so restart reconciliation can finish removal safely.

## 14. Integration lifecycle and reload policy

### 14.1 Full reloads

A full config-entry reload is reserved for global changes that alter integration-wide collectors or clients:

- Latitude
- Longitude
- Perenual API key
- Perenual access level
- Trefle token
- Update interval

### 14.2 Plant CRUD

Plant CRUD never reloads the config entry.

```text
Plant storage mutation
↓
Update runtime plant collection
↓
Update subscriptions
↓
Add, update, or remove affected entities
↓
Schedule local evaluation
↓
Persist runtime state
```

Adding or editing one plant does not interrupt unrelated plant entities.

### 14.3 Dynamic entities

Loaded platforms retain their `async_add_entities` callbacks or subscribe to coordinator plant-set changes.

```text
Coordinator plant set changes
↓
Platform compares known and current UUIDs
↓
New UUIDs
↓
async_add_entities(...)
```

Existing entities are not recreated.

## 15. Event-driven physical processing

Plant Helper uses `async_track_state_change_event()` for configured physical sensor entity IDs.

Tracked inputs:

```text
soil_moisture
soil_temperature
humidity_sensor
lux
battery
```

### 15.1 Event path

```text
Physical state changes
↓
Identify affected plants
↓
Read latest cached physical states
↓
Read cached Open-Meteo vector
↓
Run local plant evaluation
↓
Update coordinator memory
↓
Notify affected entities
```

No external request is made on this path.

### 15.2 Event coalescing

Use a per-plant debounce window of 250–500 ms. Multiple rapid sensor updates result in one evaluation using the newest states.

### 15.3 Material changes

Ignore events that do not materially alter usable input, such as an identical normalized numeric value or irrelevant attribute-only changes.

### 15.4 Listener ownership

Each runtime plant owns unsubscribe callbacks for its configured physical entities. Sensor edits cancel old callbacks, register new callbacks, and trigger one immediate evaluation. All callbacks are cancelled on integration unload.

## 16. Periodic coordinator responsibilities

Periodic processing remains separate from immediate sensor reaction.

Periodic work includes:

- Refreshing Open-Meteo when weather cache expires
- Time-based care transitions
- Duration conditions
- Calibration timing
- Stale physical telemetry detection
- Sample persistence
- Permitted background retries
- Entity changes caused by elapsed time

Hybrid model:

```text
Physical changes
→ immediate local evaluation

Time and weather changes
→ periodic coordinator evaluation
```

## 17. Runtime generation protection

Each plant runtime has a monotonic generation number. An evaluation captures the generation at start and discards its result if configuration changed before completion.

The weather cache also tracks:

```text
weather_generation
weather_observed_at
weather_fetched_at
```

Sensor-triggered evaluation records the weather generation used without fetching new weather.

## 18. Placement model

Every plant has one placement:

```text
indoor
outdoor
```

Placement controls interpretation, not whether Open-Meteo is active.

## 19. Learned state and rolling samples

### 19.1 Independent baselines

```text
plant_uuid:
  baselines:
    indoor:
      calibration state
      learned values
      confidence metadata
      last valid update
    outdoor:
      calibration state
      learned values
      confidence metadata
      last valid update
```

### 19.2 Active rolling buffer

```text
plant_uuid:
  active_runtime:
    placement
    rolling moisture samples
    rolling temperature samples
    rolling humidity samples
    rolling light samples
    pending duration timers
```

Placement change clears the active rolling buffer and placement-sensitive timers, but preserves both persisted placement baselines.

## 20. Placement transitions

### 20.1 Indoor to outdoor

After successful persistence:

- Activate outdoor weather interpretation
- Activate rain suppression
- Activate radiation-based outdoor light evaluation
- Activate wind and drying-pressure logic
- Activate outdoor exposure conditions
- Activate ozone context
- Switch to outdoor baseline
- Resume calibration if needed
- Clear active rolling samples
- Reset placement-sensitive timers

### 20.2 Outdoor to indoor

After successful persistence:

- Disable rain suppression
- Disable outdoor radiation as direct plant light
- Disable wind-based drying
- Disable outdoor hazards
- Disable ozone context
- Switch to indoor baseline
- Resume calibration if needed
- Require physical lux for measured indoor light
- Clear active rolling samples
- Reset placement-sensitive timers

## 21. Open-Meteo architecture

Plant Helper uses two independent Open-Meteo sub-collectors because weather forecasts and air-quality forecasts are separate services with distinct endpoints, refresh schedules, caches, failures, and consumers.

```text
OpenMeteoManager
├── ForecastCollector
│   ├── Base service: Weather Forecast API
│   ├── Purpose: weather, radiation, precipitation, drying, frost, and seasonal context
│   ├── Cache: forecast_weather
│   └── Consumers: indoor and outdoor plant engines
└── AirQualityCollector
    ├── Base service: Air Quality API
    ├── Purpose: modelled outdoor ozone, and only explicitly approved future air-quality context
    ├── Cache: air_quality
    └── Consumers: outdoor plant engine only
```

The Forecast collector uses one shared request for all configured plants at the selected global location:

```text
Configured latitude and longitude
↓ when absent
Home Assistant latitude and longitude
↓
Canonical coordinate normalization
↓
One Forecast API request
↓
Validated forecast-weather cache
↓
Indoor and outdoor interpretation
```

The Air Quality collector runs independently and never blocks, delays, enlarges, or changes the Forecast request. A failure in one collector does not change the freshness or availability of the other collector.

Use default `models=auto` / Best Match for forecast weather. Do not expose weather-model selection in the first version.

### 21.0 Collector independence contract

```text
Forecast refresh due
→ run ForecastCollector only

Air-quality refresh due
→ run AirQualityCollector only

Forecast failure
→ preserve stale forecast cache
→ AirQualityCollector remains eligible to run

Air-quality failure
→ preserve stale air-quality cache
→ ForecastCollector remains eligible to run
```

Each sub-collector owns its own:

- HTTP client operation
- Endpoint builder
- Request lock
- Freshness timestamp
- Failure counter
- Backoff schedule
- Last valid payload
- Normalized cache generation
- Diagnostic status

Plant evaluation reads a combined immutable environmental snapshot assembled from the latest valid generation of each cache. Missing or stale air quality must never make otherwise valid forecast weather unavailable.

### 21.1 Request horizon

```text
Current conditions: current timestep
Recent history: past_hours=24
Hourly forecast: forecast_hours=48
Daily forecast: forecast_days=7
Timezone: auto
Cell selection: land
Temperature unit: celsius
Wind speed unit: kmh
Precipitation unit: mm
```

### 21.1.1 Coordinate normalization and cache keys

Coordinates can originate from either the Plant Helper override or Home Assistant core configuration. Before a coordinate is used in an endpoint URL or weather-cache key, both latitude and longitude are converted to finite floats and rounded to three decimal places.

```text
raw latitude, longitude
↓
validate finite and in range
↓
round(value, 3)
↓
canonical location tuple
↓
request parameters and cache key
```

Example:

```text
57.7210347, 12.9398188
→
57.721, 12.940
```

Three decimal places provide roughly 0.001 degree spatial precision, approximately 110 metres for latitude, while avoiding cache misses caused only by insignificant floating-point differences. The exact spatial distance represented by longitude varies with latitude.

Canonical cache key:

```text
(latitude_3dp, longitude_3dp, timezone, request_profile_version)
```

Rules:

- The same canonical coordinates are sent to both Open-Meteo sub-collectors.
- The original configured coordinates remain stored in configuration and are not destructively rounded.
- Changing a coordinate without changing its three-decimal canonical value does not invalidate environmental caches.
- Changing the canonical location invalidates both Forecast and Air Quality caches.
- The cache key includes a request-profile version so changing requested variables or normalization behavior cannot reuse an incompatible payload.
- Returned model-grid coordinates and elevation remain response metadata and never replace configured coordinates or the canonical request key.

### 21.2 Current variables

```text
temperature_2m
relative_humidity_2m
dew_point_2m
apparent_temperature
precipitation
rain
showers
snowfall
weather_code
cloud_cover
wind_speed_10m
wind_gusts_10m
shortwave_radiation
vapour_pressure_deficit
is_day
```

### 21.3 Hourly variables

```text
temperature_2m
relative_humidity_2m
dew_point_2m
apparent_temperature
precipitation
precipitation_probability
rain
showers
snowfall
weather_code
cloud_cover
visibility
wind_speed_10m
wind_gusts_10m
shortwave_radiation
sunshine_duration
vapour_pressure_deficit
et0_fao_evapotranspiration
evapotranspiration
soil_temperature_0cm
soil_temperature_6cm
soil_moisture_0_to_1cm
soil_moisture_1_to_3cm
freezing_level_height
is_day
```

### 21.4 Daily variables

```text
weather_code
temperature_2m_max
temperature_2m_min
apparent_temperature_max
apparent_temperature_min
precipitation_sum
rain_sum
showers_sum
snowfall_sum
precipitation_hours
precipitation_probability_max
wind_speed_10m_max
wind_gusts_10m_max
shortwave_radiation_sum
sunrise
sunset
daylight_duration
sunshine_duration
et0_fao_evapotranspiration
uv_index_max
growing_degree_days_base_0_limit_50
leaf_wetness_probability_mean
relative_humidity_2m_max
relative_humidity_2m_min
vapour_pressure_deficit_max
```

## 22. Indoor Open-Meteo use

Indoor plants use only meaningful external context.

### 22.1 External daylight opportunity

Use:

```text
shortwave_radiation
shortwave_radiation_sum
cloud_cover
sunshine_duration
sunrise
sunset
daylight_duration
is_day
```

With a physical light sensor, physical lux is actual plant light and Open-Meteo is external daylight context. Without physical lux, the state is `no_light_sensor`; external radiation cannot fabricate indoor light.

### 22.2 Seasonal temperature context

Use:

```text
temperature_2m
temperature_2m_max
temperature_2m_min
growing_degree_days_base_0_limit_50
```

This supports broad seasonal and dormancy context but never represents measured room temperature.

### 22.3 External humidity context

Use:

```text
relative_humidity_2m
dew_point_2m
relative_humidity_2m_max
relative_humidity_2m_min
```

This supports seasonal context but never represents measured room humidity.

### 22.4 Indoor exclusions

Indoor plants do not use:

- Severe-weather or hazard logic
- Rain suppression
- Precipitation probability for care
- Wind-based drying
- Outdoor ET₀ or evapotranspiration
- Outdoor VPD as plant VPD
- Modelled soil moisture or soil temperature
- Leaf wetness
- Outdoor ozone
- Outdoor UV exposure
- Outdoor radiation as measured indoor light

## 23. Outdoor Open-Meteo use

### 23.1 Drying pressure

Use:

```text
temperature_2m
relative_humidity_2m
vapour_pressure_deficit
wind_speed_10m
wind_gusts_10m
shortwave_radiation
et0_fao_evapotranspiration
evapotranspiration
```

Physical soil moisture and learned dry-down remain authoritative.

### 23.2 Rain suppression

Use:

```text
precipitation
rain
showers
snowfall
precipitation_probability
precipitation_sum
rain_sum
showers_sum
snowfall_sum
precipitation_hours
precipitation_probability_max
```

Maintain derived windows:

```text
Trailing precipitation: 6h and 24h
Forecast precipitation: next 6h, 12h, and 24h
Daily context: today and tomorrow
```

Physical critical dryness can override weak or uncertain forecast suppression.

### 23.3 Outdoor light

Use radiation, cloud cover, sunshine duration, daylight, and UV context. A physical outdoor light sensor is authoritative when configured; otherwise radiation provides direct outdoor context in W/m² without fake lux conversion.

### 23.4 Frost and cold

Use 2-metre temperatures, apparent temperatures, freezing-level height, snowfall, and WMO codes. Local 2-metre minimum temperature remains the primary frost signal.

### 23.5 Leaf wetness and fungal context

Use modelled leaf wetness, humidity, dew point, precipitation duration, and cloud cover. This may create a wet-foliage or fungal-risk context but never a disease diagnosis.

### 23.6 Growth season

Use growing-degree days, temperature, daylight, sunshine duration, and radiation sum as long-term seasonal context.

## 24. Outdoor exposure conditions

Plant Helper derives plant exposure conditions, not official public warnings.

Possible categories:

```text
none
heat
frost
hard_freeze
strong_wind
heavy_rain
saturation
heavy_snow
freezing_precipitation
thunderstorm
hail
high_uv
low_visibility
```

### 24.1 WMO groups

#### Freezing exposure

```text
48, 56, 57, 66, 67
```

#### Heavy precipitation exposure

```text
55, 65, 75, 82, 86
```

#### Thunderstorm and hail exposure

```text
95, 96, 99
```

Weather code is combined with numeric precipitation, wind, temperature, snow, UV, and visibility thresholds.

### 24.2 Initial numeric thresholds

```text
Elevated wind exposure: gust >= 50 km/h
High wind exposure: gust >= 70 km/h
Elevated heat: temperature >= 30 °C
High heat: temperature >= 35 °C
Frost: minimum temperature <= 0 °C
Hard freeze: minimum temperature <= -5 °C
```

These are implementation constants covered by tests, not first-version user options.

## 25. Modelled soil data

Open-Meteo shallow soil values provide regional outdoor context only.

Initial requested layers:

```text
soil_temperature_0cm
soil_temperature_6cm
soil_moisture_0_to_1cm
soil_moisture_1_to_3cm
```

They may support regional surface wetness, drought, saturation, frost, and thaw context.

They never:

- Replace physical soil moisture
- Calibrate a physical sensor
- Become the plant moisture state
- Determine watering alone
- Apply to indoor plants
- Override learned behavior

## 26. Open-Meteo Air Quality API

The Air Quality API is implemented as an independent `AirQualityCollector`, not as additional variables in the Weather Forecast request.

### 26.1 Endpoint separation

```text
ForecastCollector
→ Weather Forecast API service
→ forecast-weather request and cache

AirQualityCollector
→ Air Quality API service
→ air-quality request and cache
```

The collectors share only canonical location input and the final read-only environmental snapshot. The collectors do not share request locks, response schemas, freshness, failure counters, or backoff state.

### 26.2 Activation

The Air Quality collector runs only when:

```text
at least one outdoor plant exists
and
no configured physical ozone sensor is selected
and
modelled ozone has a defined outdoor consumer
```

If a physical ozone entity is configured, the physical source is authoritative and modelled ozone requests are disabled. Removing the physical ozone entity can re-enable modelled ozone on the next air-quality refresh cycle.

### 26.3 Initial request

Initial design requests:

```text
current:
  ozone
hourly:
  ozone
forecast_hours: 48
past_hours: 24
timezone: auto
```

Modelled ozone supports broad outdoor foliage-stress context only. Plant Helper does not diagnose ozone injury and does not represent regional model output as a leaf-level measurement.

Potential future variables require a separately approved care consumer:

```text
dust
aerosol_optical_depth
```

Do not initially request:

```text
pollen
PM2.5
PM10
CO
NO2
SO2
European AQI
US AQI
```

Regional outdoor air quality never represents indoor air quality.

### 26.4 Independent refresh and failure behavior

```text
Normal refresh: 60 minutes
Minimum refresh after success: 30 minutes
Temporary failure backoff: 15m → 30m → 60m → 120m
Physical sensor event: no air-quality request
No outdoor plants: collector stopped and cache retained as stale metadata only
Physical ozone configured: collector stopped
```

A Forecast API failure does not suppress an eligible Air Quality refresh. An Air Quality failure does not affect forecast-weather availability, indoor evaluation, rain suppression, radiation, frost, or outdoor drying calculations.

### 26.5 Independent cache

```text
air_quality_cache:
  location_key
  current:
    observed_at
    ozone
  hourly:
    start
    end
    ozone
  derived:
    ozone_current
    ozone_max_12h
    ozone_max_24h
  metadata:
    fetched_at
    expires_at
    generation
    failure_count
```

The combined environmental snapshot may contain both caches, but each value retains source and observation time internally.

## 27. Satellite Radiation API

Satellite radiation is an optional future enhancement, not a first-version dependency. The weather model contract supports a future radiation source distinction:

```text
forecast_model
satellite_observed
```

Initial implementation uses `shortwave_radiation` from the Forecast API.

## 28. Conditional Open-Meteo request composition

### 28.1 Indoor plants only

Request only indoor-consumed fields:

- Temperature
- Humidity
- Dew point
- Cloud cover
- Radiation
- Sunshine duration
- Sunrise
- Sunset
- Daylight duration
- Growing degree days
- Is day

### 28.2 At least one outdoor plant

Request the full selected weather vector, adding precipitation, probability, weather codes, wind, gusts, VPD, ET₀, evapotranspiration, shallow soil context, freezing level, visibility, UV, and leaf wetness.

### 28.3 No plants

Do not call Open-Meteo.

## 29. Weather refresh policy

```text
Normal forecast refresh: 30 minutes
Minimum refresh after success: 15 minutes
Temporary failure backoff: 5m → 15m → 30m → 60m
Physical sensor event: no weather request
```

Weather fetching and plant evaluation intervals are separate.

## 30. Forecast weather cache

The Forecast collector owns this cache independently from the Air Quality cache.

```text
forecast_weather_cache:
  location:
    latitude
    longitude
    elevation
    timezone
  current:
    observed_at
    values
  hourly:
    start
    end
    values
  daily:
    start
    end
    values
  derived:
    precipitation_6h
    precipitation_24h
    forecast_precipitation_6h
    forecast_precipitation_12h
    forecast_precipitation_24h
    max_precipitation_probability_12h
    et0_24h
    evapotranspiration_24h
    radiation_24h
    daylight_today
    frost_next_24h
    maximum_gust_next_24h
    maximum_vpd_next_12h
    mean_leaf_wetness_today
    outdoor_hazards
  metadata:
    fetched_at
    expires_at
    generation
    model_coordinates
    model_elevation
```

## 31. External species enrichment

### 31.1 Provider roles

#### Perenual

Preferred for practical care context:

- Watering category
- Sunlight requirements
- Indoor suitability
- Humidity preference
- Temperature preference
- Soil context
- Hardiness
- Lifecycle
- Growth characteristics
- Pruning guidance
- Common name
- Image

#### Trefle

Preferred for taxonomy:

- Accepted scientific name
- Common name
- Family
- Genus
- Rank
- Status
- Synonyms
- Authorship
- Botanical image

#### iNaturalist

Used for taxon confirmation, common name, rank, ancestor context, and suitable taxon image.

Perenual and Trefle activate only when credentials are configured. Public iNaturalist enrichment is always enabled.

## 32. Species matching and merge

Provider candidates are classified:

```text
confirmed
strong
ambiguous
rejected
```

Only confirmed and strong matches contribute data.

Matching evidence includes exact scientific name, exact common name, exact synonym, accepted status, genus agreement, family agreement, and normalized token similarity.

Results merge field by field. No provider replaces the complete normalized species record.

## 33. Normalized species model

```text
identity:
  configured_species
  scientific_name
  common_name
  family
  genus
  taxonomic_rank
  taxonomic_status
  synonyms
care:
  watering_category
  sunlight_requirements
  indoor_suitability
  soil_requirements
  minimum_temperature
  maximum_temperature
  humidity_preference
  pruning_guidance
  growth_habit
  lifecycle
  hardiness
presentation:
  image_url
  image_source
provenance:
  identity_source
  taxonomy_source
  care_sources
  image_source
  last_successful_refresh
```

Raw payloads, empty values, upgrade messages, advertisements, HTML, iframes, placeholder images, provider error text, secrets, and credential-bearing URLs are excluded.

## 34. Species cache and API frequency

```text
Complete merged record: 90 days
Stable complete taxonomy: 180 days
Partial enrichment: 30 days
Valid taxonomy without image: image retry after 30 days
No acceptable match: 14 days
Temporary failure: 1h → 6h → 24h
Authentication failure: wait for configuration correction
Rate limiting: provider reset or 1h → 6h → 24h
```

Normal coordinator updates never call species providers.

Refresh triggers:

- Uncached species added
- Species changed
- Cache expired
- Provider credential changed
- Perenual access level changed
- Manual refresh requested

## 35. Enrichment single-flight

The enrichment manager owns:

```python
in_flight: dict[str, asyncio.Future]
```

The key is the normalized species string. Followers await the existing future rather than dispatching duplicate requests. The entry is removed in `finally` after success, failure, or cancellation.

A provider-specific map keyed by `(normalized_species, provider)` prevents duplicate partial refreshes.

## 36. Negative cache classification

Fourteen-day negative caching applies only to valid completed lookups with no acceptable match.

Eligible:

- Successful empty search
- Successful search where every candidate is rejected
- Semantic not-found response

Not eligible:

- 401 or 403
- 429
- 5xx
- Timeout
- DNS or TLS failure
- Connection reset
- Invalid JSON
- Unexpected response structure
- Provider maintenance
- Cancellation

## 37. Shared species cache

Species enrichment belongs to normalized species identity, not individual plants. Multiple plants using the same species share one cached record and one refresh operation.

The cache supports:

- Confirmed aliases
- Single-flight enrichment
- Stale-while-refresh
- Field-level freshness
- Provider-specific backoff
- Content fingerprints

Unchanged normalized results do not rewrite storage or cause entity churn.

## 38. Species changes and learning

A confirmed alias or taxonomic correction preserves learned baselines.

A change to a different taxon preserves plant UUID and entity identity, but clears active rolling samples and starts fresh calibration for species-sensitive values. The exact species-sensitive baseline fields are defined in the learning implementation plan.

## 38.1 Species image proxy and local cache

Raw third-party image URLs are never exposed directly as the primary dashboard image URL. Plant Helper downloads, validates, transforms, and serves a local cached thumbnail.

### 38.1.1 Download rules

The image fetcher accepts only:

- HTTPS source URLs
- HTTP 200 responses
- Declared image content types
- Bounded response size
- Bounded dimensions
- Static image formats approved by the implementation
- Redirects that remain HTTPS and pass the same host and address validation

The fetcher rejects:

- Plain HTTP images
- Private, loopback, link-local, multicast, and reserved destination addresses
- Non-image content
- SVG or active content unless explicitly sanitized by an approved image pipeline
- Oversized files
- Excessive dimensions or decompression bombs
- Credential-bearing URLs
- Provider placeholders

DNS resolution and redirect targets are validated to prevent server-side request forgery.

### 38.1.2 Cache representation

```text
species_image_cache:
  image_hash
  source_provider
  source_fingerprint
  retrieved_at
  content_type
  width
  height
  byte_size
  local_filename
```

Recommended stored rendition:

```text
Format: WebP or JPEG
Maximum edge: 1024 px
Thumbnail edge: 512 px
Metadata: stripped
Animated content: converted to static first frame or rejected
```

Files are content-addressed by a hash of validated image bytes, not by raw source URL. Identical images from multiple records share one cached file.

### 38.1.3 Home Assistant serving strategy

Preferred first-version strategy:

```text
Authenticated Home Assistant HTTP view:
/api/plant_helper/image/<image_hash>
```

The view:

- Requires an authenticated Home Assistant request
- Accepts only a strict hexadecimal hash path parameter
- Resolves only files inside the integration image-cache directory
- Never accepts an arbitrary URL or filesystem path
- Sets the correct image content type
- Sets cache headers and an ETag based on the content hash
- Returns 404 for unknown or removed images

An integration media source may replace the HTTP view later if the target Home Assistant version provides a better supported presentation path. The public species model exposes the local authenticated path, while the original provider URL remains internal provenance only.

### 38.1.4 Refresh and cleanup

- Image refresh is independent from taxonomy freshness.
- A failed refresh preserves the previous valid local image.
- Unreferenced images are garbage-collected after a retention period.
- Image download failure never affects plant availability.
- Provider attribution remains available internally and in user-facing attribution where required.
- CORS and provider hotlinking restrictions are avoided because dashboards retrieve the image from Home Assistant itself.

## 39. Entity design

Entities must have clear user value, stable identity, appropriate units and device classes, and minimal useful attributes.

Plant-level concepts include:

- Care status
- Health
- Moisture
- Light
- Temperature
- Calibration
- Species context
- Selected diagnostics

Do not expose:

- Raw provider responses
- Match scores
- Cache keys
- Request counters on every plant
- Provider headers
- Raw samples
- Learning windows
- Internal thresholds without user meaning
- API secrets
- Debug state

Provider failure or stale enrichment does not make plant entities unavailable.

## 40. Compact API diagnostics

Possible integration-level diagnostic values:

```text
enrichment state
last successful enrichment
available provider count
weather cache state
last successful weather refresh
```

Detailed provider errors, match scoring, and backoff remain internal or appear only in redacted diagnostics.

## 41. Runtime processing pipeline

```text
Load global settings
↓
Load plants
↓
Load learned baselines and samples
↓
Build runtime plant objects
↓
Register physical listeners
↓
Set up dynamic entities
↓
Load cached weather
↓
Refresh weather if stale
↓
Read physical sensors
↓
Read cached species context
↓
Build normalized runtime vectors
↓
Apply placement rules
↓
Apply learning and calibration
↓
Publish entity states
```

Species enrichment runs independently in a bounded background queue.

Recommended limits:

```text
Concurrent species enrichments: 2
Per-provider concurrency: 1
```

## 42. Error contract

Required translated errors:

```text
invalid_global_settings
cannot_load_storage
cannot_save_plant
cannot_remove_plant
plant_changed
plant_not_found
no_plants
name_required
moisture_required
moisture_not_numeric
moisture_out_of_range
custom_multiplier_range
single_instance_allowed
```

Every recoverable failure keeps the form usable, preserves submitted values, displays a translated error, permits retry, and performs no false success action.

## 43. Privacy and security

Secrets never appear in:

- Entity states
- Entity attributes
- Diagnostics
- Logs
- User-facing exceptions
- Stored URLs
- Test fixtures
- Service responses
- Provider provenance

Request logging redacts query-string credentials and authorization headers.

## 44. Behavioral test strategy

Tests must execute through the actual Home Assistant flow manager for the target version. Source inspection can supplement but not replace behavior tests.

### 44.1 Setup

- Setup opens without HTTP 400
- Every selector serializes
- Empty optional values work
- Valid values create one entry
- Duplicate setup aborts
- Invalid values produce field errors
- Runtime receives configured options

### 44.2 Reconfigure

- Current values populate
- Every field changes
- Every optional field clears
- Cleared values remain absent
- Invalid saved values cannot break loading
- Runtime receives new values
- Exactly one reload occurs
- Failure causes no update or reload

### 44.3 Add

- Menu and form open
- Required validation works
- Every sensor field persists
- UUID identity is created
- Duplicate names work
- Storage failure stays on form
- Provider failure does not block creation
- Runtime and entities are added without reload

### 44.4 Edit

- Complete record populates
- Optional fields clear
- UUID and entity identity remain stable
- Stale concurrent flow cannot overwrite newer data
- Storage failure preserves existing state
- Listener set updates
- Placement transition runs only after persistence
- Runtime updates without reload

### 44.5 Remove

- Confirmation is required
- Cancellation changes nothing
- Storage failure preserves everything
- Successful removal cancels listeners, removes runtime, entities, registry entries, device, learned state, and samples
- No global reload occurs

### 44.6 Sensor events

- Relevant physical changes trigger immediate evaluation
- Rapid changes coalesce
- No event calls external APIs
- Cached weather is used
- Listener edits work
- Unload removes every listener

### 44.7 Indoor behavior

- Open-Meteo external daylight and seasonal context are used
- Outdoor weather is never exposed as physical indoor telemetry
- No rain suppression
- No severe-weather behavior
- No ozone behavior
- No wind-based drying
- Missing lux gives `no_light_sensor`
- Indoor baseline remains independent

### 44.8 Outdoor behavior

- Radiation supports outdoor light
- Rain suppression works
- Probability windows work
- VPD, ET₀, wind, and radiation support drying context
- Frost and exposure conditions work
- Ozone behavior works
- Shallow modelled soil remains contextual
- Outdoor baseline remains independent

### 44.9 Open-Meteo

- Conditional request composition works
- No plants means no request
- Current, hourly, and daily units validate
- Time alignment is correct
- Past and forecast windows derive correctly
- API 400, 429, 5xx, timeout, malformed JSON, and missing fields recover safely
- Stale weather remains usable during refresh failure
- Sensor events never bypass weather cache freshness

### 44.10 Species providers

- Exact and strong matching
- Ambiguous rejection
- Field-level merge
- Free and paid Perenual behavior
- Trefle limits
- iNaturalist image validation
- Shared cache
- Single-flight
- Stale-while-refresh
- Negative cache classification
- Authentication suspension
- Backoff
- Credential redaction
- Provider failure never affects plant availability

### 44.11 Storage, registry, coordinates, and images

- Top-level storage version increments exactly once per successful write
- Per-plant revision rejects stale edit and remove flows
- Unrelated species-cache writes do not falsely overwrite plant changes
- Compare-and-write is atomic under the storage lock
- Dynamic removal calls entity lifecycle removal before registry deletion
- Entity registry entries are removed before the device
- Partial cleanup is idempotent and restart-reconcilable
- Forecast and Air Quality collectors refresh independently
- A failure in one Open-Meteo endpoint does not block the other
- Three-decimal canonical coordinates produce stable request and cache keys
- Original configured coordinate precision remains preserved
- Coordinate changes crossing a canonical boundary invalidate both environmental caches
- Image downloads reject HTTP, private addresses, invalid redirects, non-images, and oversized payloads
- Cached images are served only through authenticated hash-based local paths
- Image refresh failure preserves the previous valid local image

### 44.12 Packaging

- Python compilation
- Translation JSON parsing
- Manifest validation
- No compiled caches
- Complete tests pass from extracted ZIP
- Recovery script recreates exact ZIP
- No flow test skipped

## 45. Build plan

1. Finalize this design contract
2. Write the complete behavioral test matrix
3. Build the Home Assistant 2025.12.2 test environment
4. Implement pure configuration and validation models
5. Implement initial setup
6. Implement reconfigure
7. Implement plant-management menu
8. Implement runtime collection and dynamic entities
9. Implement Add plant
10. Implement Edit plant
11. Implement Remove plant
12. Implement event-driven physical processing
13. Implement independent placement learning
14. Implement Forecast and Air Quality sub-collectors with independent caches
15. Implement canonical coordinate keying and environmental snapshot assembly
16. Implement indoor interpretation
17. Implement outdoor interpretation
18. Implement optimistic storage locking and dynamic registry reconciliation
19. Implement species enrichment, image proxy, and caches
20. Connect the preserved public entity contract
21. Run complete regression and compatibility verification
22. Package the release and exact recovery script

## 46. Acceptance criteria

The design is accepted when all of the following are true:

- Setup and reconfigure render reliably
- No flow produces a blank error
- Plant CRUD requires no integration reload
- Global reconfigure reloads exactly once
- Physical changes evaluate immediately without network calls
- Plant identity is immutable and UUID-based
- Duplicate names work
- Placement baselines remain independent
- Placement changes clear only active rolling samples
- Forecast and Air Quality Open-Meteo sub-collectors are shared across plants but fail and refresh independently
- Canonical three-decimal coordinate keys prevent insignificant floating-point cache misses
- Indoor plants use only useful external daylight and seasonal context
- Outdoor plants use weather for rain, drying, light, frost, wetness, hazards, and seasonality
- Modelled soil values remain contextual
- Species providers are static cached enrichment only
- Species images render through a validated authenticated local cache path rather than provider hotlinks
- Storage revisions prevent stale flow commits
- Dynamic removal leaves no ghost entities or orphan plant devices
- All optional settings and sensors can be cleared
- Storage failures never report success
- Provider and weather failures never erase valid cached data
- Entities remain stable across configuration changes
- Secrets remain private
- Every behavior has an executable test
- No required flow test is skipped

## 47. References

- Home Assistant Config Flow documentation: https://developers.home-assistant.io/docs/core/integration/config_flow/
- Home Assistant Options Flow documentation: https://developers.home-assistant.io/docs/core/integration/options_flow/
- Home Assistant event-listener documentation: https://developers.home-assistant.io/docs/integration_listen_events/
- Home Assistant dynamic-device guidance: https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/dynamic-devices/
- Home Assistant entity documentation: https://developers.home-assistant.io/docs/core/entity/
- Open-Meteo Weather Forecast API: https://open-meteo.com/en/docs
- Open-Meteo Air Quality API: https://open-meteo.com/en/docs/air-quality-api
- Open-Meteo Satellite Radiation API: https://open-meteo.com/en/docs/satellite-radiation-api
- Perenual API documentation: https://perenual.com/docs/api
- Trefle API documentation: https://docs.trefle.io/
- iNaturalist API recommended practices: https://www.inaturalist.org/pages/api+recommended+practices
