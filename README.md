# Plant Helper

[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-Custom%20Integration-41BDF5?logo=home-assistant&logoColor=white)](https://www.home-assistant.io/)
[![HACS](https://img.shields.io/badge/HACS-Custom%20Repository-41BDF5)](https://hacs.xyz/)
[![Version](https://img.shields.io/badge/version-4.4.14-blue)](custom_components/plant_helper/manifest.json)

Plant Helper is a Home Assistant custom integration that turns soil-moisture, soil-temperature, and light readings into calibrated, time-based plant-care guidance. It learns how each plant behaves in its actual location and combines that local history with optional solar-radiation data, weather forecasts, and read-only species context.

> **Current release:** Version 4.4.14. See the changelog for release history.

## Highlights

- UI-based setup and plant management
- Independent indoor and outdoor learned baselines
- Fourteen-day calibration that extends when evidence is incomplete
- Conservative post-calibration adaptation of the saturated-moisture peak
- Profile-aware dry-threshold regeneration
- Gap-aware validation that avoids learning across missing or invalid telemetry
- Restart-safe calibration, samples, timers, daily history, and learned state
- STRÅNG solar radiation in Nordic coverage
- Source-isolated estimated Open-Meteo radiation fallback elsewhere
- Optional Home Assistant or Open-Meteo weather forecasts
- Bounded outdoor ET₀ drying-pressure adjustment
- Precipitation-probability-aware rain suppression
- Weather hazards, ozone advisory, dormancy, and species context
- Plant-level care, health, moisture, light, temperature, calibration, species, and diagnostic entities

## Requirements

- A recent Home Assistant release
- One soil-moisture sensor per plant
- Optional soil-temperature, illuminance, and battery sensors
- Optional Home Assistant weather forecast entity
- Optional internet access for STRÅNG, Open-Meteo, and species providers

Physical plant sensors remain authoritative. Modelled Open-Meteo soil values are regional context only and never replace or calibrate a local plant sensor.

## Installation

### HACS custom repository

Until Plant Helper is available through the default HACS catalogue:

1. Open **HACS**.
2. Select **Integrations**.
3. Open the menu and select **Custom repositories**.
4. Add `https://github.com/swetoast/ha-plant-helper` as an **Integration** repository.
5. Install **Plant Helper**.
6. Restart Home Assistant.
7. Open **Settings > Devices & services > Add integration**.
8. Select **Plant Helper**.

### Manual installation

1. Copy `custom_components/plant_helper` into your Home Assistant configuration directory.
2. Restart Home Assistant.
3. Open **Settings > Devices & services > Add integration**.
4. Select **Plant Helper**.

## Configuration

### Global settings

Plant Helper exposes these shared options:

- **Latitude and longitude:** optional overrides for the Home Assistant location used by outdoor weather and radiation data
- **Ozone sensor:** optional sensor used for the outdoor ozone advisory
- **Perenual API key:** optional species context
- **Perenual access level:** choose **Free** or **Paid** to match the API plan connected to the key
- **Trefle API token:** optional botanical fallback context
- **Update interval:** default 300 seconds, accepted range 60–3600 seconds
- **Radiation source:** selected automatically from location coverage; no user-facing selector is exposed in version 4.4.14

#### Perenual access levels

Select the access level that matches the Perenual account:

- **Free:** uses search results as useful species context, avoids detail requests for plant IDs above 3000, and ignores upgrade-only placeholders returned by the service.
- **Paid:** allows detail requests for all returned plant IDs.

An upgrade-related HTTP 429 response is treated as a plan restriction rather than a general rate-limit event. Actual rate limiting still applies normal provider backoff. Changing the access level or API key invalidates incompatible cached Perenual data so the next refresh uses the current settings.

Perenual, Trefle, and iNaturalist data is read-only context. Provider data does not replace the configured sensors or rewrite learned care thresholds.

### Outdoor weather and radiation behavior

Plant Helper uses the Home Assistant location unless latitude and longitude overrides are provided. Open-Meteo supplies shared forecast context for outdoor plants, including precipitation, weather conditions, and ET0 drying pressure. There is no user-facing weather-source selector in version 4.4.14.

For radiation, Plant Helper prefers the direct STRANG API when the configured location is inside its supported Nordic coverage. Outside that coverage it uses source-isolated estimated PAR derived from Open-Meteo shortwave radiation. Radiation histories use separate storage keys so one daily-light calculation cannot mix providers within the same calendar day.

### Per-plant settings

- **Plant name:** required display name and stable plant identifier basis
- **Species:** optional read-only provider context
- **Soil moisture:** required percentage sensor
- **Soil temperature:** optional temperature compensation and thermal context
- **Light (lux):** optional indoor light adequacy and obstruction detection
- **Battery level:** optional numeric or categorical battery source
- **Placement:** indoor or outdoor
- **Care profile:** dry tolerant, balanced, moisture loving, or custom
- **Rain threshold:** optional outdoor rain-suppression threshold

## Calibration and learning

Each placement has its own learned baseline. Moving a plant between indoor and outdoor locations does not erase the other placement's data.

A placement begins with a fourteen-day calibration period. If the required evidence is incomplete, calibration extends instead of locking a partial baseline. The Health sensor is unavailable during calibration, while the separate **Calibration** diagnostic reports the current learning state.

Plant Helper learns:

- saturated soil-moisture peak
- dry threshold
- drying rate
- outdoor daily-light target
- indoor window-transmission factors
- normal soil-temperature mean
- normal daily soil-temperature swing

After calibration, a validated and well-covered new moisture peak can slowly adjust the learned saturated-moisture maximum. The maximum can only move upward and uses a bounded exponentially weighted moving average. The dry threshold is then regenerated from the plant's stored standard or custom care profile.

Drying rate, daily-light target, window transmission, thermal mean, and thermal swing remain locked until dedicated bounded adaptation policies are implemented.


## Outdoor drying projection

For outdoor plants, Plant Helper combines the learned local drying rate with bounded environmental pressure:

- ET₀ around 3 mm over the next 24 hours is neutral
- ET₀ influence is limited to 0.85–1.15
- the final combined environmental modifier is limited to 0.60–1.15
- missing, stale, invalid, or indoor ET₀ is neutral
- VPD remains diagnostic context to avoid double-counting environmental drying pressure

ET₀ changes only the current projection. It is never written into the learned baseline.

## Rain suppression

Outdoor watering guidance can be suppressed when meaningful rain is expected.

- Forecast precipitation must meet the plant's configured rain threshold.
- When probability is available, the maximum probability within 48 hours must be at least 60%.
- Low-confidence rain does not suppress watering guidance.
- Forecast providers without probability retain amount-only behavior.
- Invalid probabilities cannot suppress guidance.
- Suppression is re-evaluated during every coordinator update.

## Entities

Each configured plant exposes:

- Health
- Care action
- Moisture
- Light
- Temperature
- Calibration
- Species
- Needs water
- Weather hazard
- Sensor fault
- Light obstruction
- Dormant
- Optional ozone advisory

Hub-level diagnostics report radiation-source and species-provider health.

The Species entity is context only. Provider data cannot override calibrated plant-care decisions.

## Diagnostic attributes

Depending on placement and available sources, diagnostics can include:

- learned drying rate
- effective drying rate
- ET₀ for the next 24 hours
- ET₀ drying modifier
- forecast precipitation for the next 48 hours
- maximum precipitation probability for the next 48 hours
- active radiation source
- whether radiation is estimated
- active radiation source-lock key
- radiation data age and sample counts

## Services

### `plant_helper.recalibrate`

Restarts calibration for one configured plant by clearing the active placement's learned baseline and local sample history. The other placement's baseline and species context are preserved.

```yaml
service: plant_helper.recalibrate
data:
  plant_id: monstera_livingroom
```

### `plant_helper.refresh_species`

Refreshes read-only species context. Supply `plant_id` for one plant, or omit it to refresh every configured plant. It does not reset calibration or change care decisions.

```yaml
service: plant_helper.refresh_species
data:
  plant_id: monstera_livingroom
```

## Persistence

Plant Helper preserves:

- local sample history
- calibration progress
- indoor and outdoor learned baselines
- compact daily history
- dormancy state
- dry, wet, cold, and warm condition timers

Removing an individual plant purges its device, entities, configuration, samples, learned state, timers, and history.

## Removing the integration

1. Open **Settings > Devices & services**.
2. Open the Plant Helper integration menu.
3. Select **Delete**.
4. If installed through HACS, uninstall Plant Helper from HACS after deleting the integration entry.
5. Restart Home Assistant if requested.

## Release notes

See [CHANGELOG.md](CHANGELOG.md) for release history and notable changes.

## Weather data attribution

When Open-Meteo is selected, weather data is provided by [Open-Meteo.com](https://open-meteo.com/) under CC BY 4.0.

Open-Meteo radiation is estimated from modelled shortwave radiation and must not be treated as measured PAR. Modelled soil moisture describes regional grid-cell conditions and does not represent moisture in an individual pot or planter.

## Support

Use [GitHub Issues](https://github.com/swetoast/ha-plant-helper/issues) for reproducible bugs and feature requests. Include the Plant Helper version, Home Assistant version, relevant diagnostics, and sanitized logs.

## License

See [LICENSE](LICENSE).
