


# Plant Helper
[![Version](https://img.shields.io/badge/version-3.2.0-blue.svg)](https://github.com/swetoast/ha-plant-helper/releases)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.1+-blue.svg)](https://www.home-assistant.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz/)

A Home Assistant custom integration that turns local soil, temperature, and light sensors into calibrated, time based plant-care guidance. It can also use regional solar irradiance data and a weather forecast for outdoor plants.

Unlike threshold based plant cards, Plant Helper does not judge a plant from an instant reading. It learns each plant's normal behaviour during a two-week calibration period, then describes measured growing conditions over time. It tracks how much light the plant has accumulated, how long the soil has been dry or wet, how the room compares to the plant's learned baseline, and whether the plant has entered seasonal dormancy.

## Table of contents

1. [How it works](#how-it-works)
2. [Requirements](#requirements)
3. [Installation](#installation)
4. [Configuration](#configuration)
5. [The 14-day calibration](#the-14-day-calibration)
6. [The sensors](#the-sensors)
7. [Care profiles and placement](#care-profiles-and-placement)
8. [Services](#services)
9. [Managing plants](#managing-plants)
10. [Data persistence](#data-persistence)
11. [Known limitations](#known-limitations)
12. [Species enrichment and API diagnostics](#species-enrichment-and-api-diagnostics)
13. [Troubleshooting](#troubleshooting)

## How it works

Every 10 minutes, the integration:

1. Reads each plant's local sensors, including soil moisture, soil temperature, and light.
2. Uses shared context where available, including SMHI STRÅNG irradiance, sun elevation, and a weather forecast.
3. Stores those readings in a rolling buffer that survives restarts.
4. Runs a decision engine that produces a moisture state, light state, temperature state, dormancy flag, health score, and one prioritised care action for each plant.

The engine is built from independent models for moisture, light, temperature, dormancy, and health. A precedence ladder turns those model results into one clear recommendation, so Plant Helper does not give conflicting advice.

## Requirements

| Requirement | Why | Required |
|---|---|---|
| Home Assistant, recent release | Host | Yes |
| Per-plant soil moisture sensor | Primary care signal | Strongly recommended |
| Per-plant soil temperature sensor | Helps moisture compensation and temperature state | Recommended |
| Per-plant light sensor | Indoor light adequacy and obstruction detection | Recommended for indoor plants |
| Per-plant battery sensor | Pauses care logic on critical battery. Accepts a percentage or a categorical state such as high, middle, or low | Optional |
| SMHI STRÅNG integration | Outdoor DLI and cloud context | Required for outdoor plants |
| Weather entity or forecast sensor | Rain handling and severe-weather context | Optional, but recommended |

The engine itself is pure Python and uses only the standard library. No extra requirements are installed.

## Installation

1. Copy the `plant_helper` folder into `config/custom_components/`.
2. Restart Home Assistant.
3. Go to **Settings > Devices & Services > Add Integration > Plant Helper**.
4. Complete initial setup. API keys are optional.
5. Add plants from the integration's **Configure** screen.

## Configuration

### Global settings

Global settings are available under **Settings > Devices & Services > Plant Helper > Configure > Settings**.

| Field | Purpose |
|---|---|
| Perenual API key | Optional species context, such as common name, tips, facts, and photos |
| Trefle API token | Optional fallback species context |
| Enable Trefle fallback | Allows Trefle to be used when Perenual does not return useful data |
| Enable iNaturalist enrichment | Adds extra species context where available |
| Update interval | Poll interval in seconds. Default is 600 |
| Forecast source | A `weather.*` entity or a `sensor.*` that exposes a forecast attribute, such as a combined hourly-weather sensor |
| Ozone sensor | Optional ground-level ozone sensor in µg/m³. Used only for outdoor plant advisories |

Enrichment providers add context only. They never drive care decisions. Care decisions come from the plant's own sensors and learned baseline.

### SMHI STRÅNG sensors

The macro layer defaults to the standard STRÅNG entity IDs:

- `sensor.smhi_strang_par`
- `sensor.smhi_strang_global_irradiance`
- `sensor.smhi_strang_diffuse_irradiance`
- `sensor.smhi_strang_direct_horizontal_irradiance`
- `sensor.smhi_strang_outdoor_lux`
- `binary_sensor.smhi_strang_api_issue`

No extra configuration is needed if you use the standard names.

### Per-plant configuration

When you add a plant, you link its sensors and choose its care settings.

| Field | Notes |
|---|---|
| Soil temperature | The plant's soil temperature sensor |
| Soil moisture | The plant's soil moisture sensor |
| Room temperature | The surrounding room temperature sensor |
| Room humidity | The surrounding room humidity sensor |
| Light | The light sensor placed near the plant |
| Battery level | Optional. Critical battery pauses care logic |
| Placement | `indoor` or `outdoor`. This selects the light model |
| Care profile | `dry_tolerant`, `balanced`, `moisture_loving`, or `custom` |
| Rain suppression threshold | Outdoor only. Forecast rain above this value softens dry alerts |

### Sensor compatibility notes

- **Soil moisture:** Any sensor works whether Home Assistant exposes it as `humidity` or `moisture`. Plant Helper always treats it as plant moisture.
- **Battery:** Works with a numeric percentage or a categorical state such as `high`, `middle`, or `low`. A low or critical reading pauses care logic. An unreadable battery never falsely pauses care.
- **Light:** Any illuminance sensor can be used. A room lux sensor can also be placed near the plant.

## The 14-day calibration

When a plant is first added, or after **Recalibrate**, it enters a 14-day observation phase. During this phase, Plant Helper learns the plant's normal pattern.

It learns:

- `M_max`, the saturated moisture peak based on a rolling 3-hour average.
- `M_dry`, the dry threshold based on the selected care profile.
- The average daily drying rate.
- The outdoor DLI target for outdoor plants.
- `K_window` for indoor plants, which describes how much outdoor light the window passes per sun-elevation band.
- The expected temperature mean and normal day-night swing.

During calibration:

- Care alerts are suppressed.
- The Health sensor reads `calibrating` and has no score yet.
- If a trusted baseline cannot be learned by day 14, calibration continues instead of saving a bad baseline.

For example, if the plant was never watered during calibration, Plant Helper may not have enough data to learn a reliable drying curve.

## The sensors

Each plant becomes a Home Assistant device with the sensors below. These entities are thin readers of the decision engine. The care logic lives in the engine, not inside the entity classes.

### Sensor entities

| Sensor | State | Key attributes | How to use it |
|---|---|---|---|
| Health | `0` to `100`, or `calibrating` | `health_state`, `components`, `primary_issue`, `reason`, `dormant`, `run_days` | Main at-a-glance plant condition. Frozen during calibration and floored during dormancy |
| Care action | Example: `water_now` | `primary_issue`, `reason`, `severity` | The single most important action right now. `severity` is useful for sorting and automations |
| Moisture | Moisture state | `calculated_moisture`, `days_until_dry`, `days_since_watered`, `watering_urgency`, `suppressed_by_rain`, `days_dry`, `days_wet` | Watering guidance over time |
| Light | Light state | `light_score`, `adequacy_ratio`, `obstruction`, `source`, `light_hours_today`, `daylight_hours` | Light adequacy near the plant. `source` is `dli` for outdoor plants or `window` for indoor plants |
| Temperature | Temperature state | `drying_modifier`, `hazard`, `hazard_type`, `days_cold`, `days_warm` | Temperature comfort and drying context |
| Calibration | `calibrating` or `active` | None | Shows whether the plant is still learning or fully active |
| Species | Common name | `care_level`, `watering`, `sunlight`, `cycle`, `drought_tolerant`, `poisonous_to_pets`, `poisonous_to_humans`, `suggested_profile`, `reference_watering_days` | Reference context from enrichment providers. It never affects care decisions |

### Binary sensors

| Binary sensor | Device class | On when | How to use it |
|---|---|---|---|
| Needs water | `problem` | Care action is `water_now` or `water_soon` | Simple watering automation trigger |
| Weather hazard | `safety` | Severe weather is expected for an outdoor plant | Notify before the plant needs shelter |
| Sensor fault | `problem` | Care is paused because of critical battery or no usable sensors | Shows that the readings are the problem, not the plant |
| Light obstruction | `problem` | Indoor plant has low indoor light while outdoor light is strong | Useful for blind or obstruction reminders |
| Dormant | None | Plant appears seasonally dormant | Informational only |
| Ozone advisory | `problem` | Ground-level ozone is elevated for an outdoor plant | Advisory only. Does not change care action or health score |

The Ozone advisory sensor is only created when an ozone sensor is configured and the plant is outdoor.

### State reference

**Moisture states:** `recently_watered`, `drying_normally`, `getting_dry`, `dry_too_long`, `wet_too_long`, `normal`, `suppressed_by_rain`.

**Light states:** `normal`, `higher_daily_light`, `lower_daily_light`, `lower_3d`, `lower_this_week`, `recovering`, `unknown`.

**Temperature states:** `stable`, `cooler_than_usual`, `warmer_than_usual`, `cold_too_long`, `warm_too_long`, `swingy`, `weather_hazard_imminent`, `unknown`.

**Care actions:** `water_now`, `water_soon`, `reduce_water`, `seek_shelter`, `move_warmer`, `move_cooler`, `clear_obstruction`, `increase_light`, `check_sensor`, `monitor`, `none`.

### Example automation

```yaml
automation:
  - alias: "Plant needs water"
    trigger:
      - platform: state
        entity_id: binary_sensor.monstera_needs_water
        to: "on"
    action:
      - service: notify.mobile_app
        data:
          message: >
            {{ state_attr('sensor.monstera_care_action', 'reason') }}
```

## Care profiles and placement

Profiles set how strict the moisture rules are through the `M_dry` multiplier.

| Profile | `M_dry` | Good for |
|---|---|---|
| `dry_tolerant` | `0.25 * M_max` | Cacti, succulents, snake plants |
| `balanced` | `0.50 * M_max` | Most houseplants |
| `moisture_loving` | `0.70 * M_max` | Ferns, calatheas, tropical plants |
| `custom` | Your selected multiplier | Fine tuning |

Placement switches the light model.

### Indoor placement

Indoor plants use the Window Efficiency Ratio. This compares outdoor light with the light measured near the plant.

It helps distinguish:

- A naturally dim day, where indoor and outdoor light both drop.
- A blocked window or blind, where outdoor light is strong but plant light is low.

### Outdoor placement

Outdoor plants use Daily Light Integral from SMHI PAR data. Plant Helper compares recent outdoor light to the plant's learned target and can detect shortfalls over 1 day, 3 days, and 7 days.

A plant that moves between indoor and outdoor placement keeps separate baselines for each placement. Switching placement uses the stored baseline for that placement when available. If that placement has never been calibrated, a new calibration is needed.

## Services

### `plant_helper.recalibrate`

Recalibrates a plant by clearing its learned baseline and sample history.

Use this after:

- Repotting
- Changing soil composition
- Moving the plant to a different room
- Moving the plant between indoor and outdoor placement

```yaml
service: plant_helper.recalibrate
data:
  plant_id: monstera_livingroom
```

## Managing plants

All plant management is under **Settings > Devices & Services > Plant Helper > Configure**.

Available actions:

- **Add Configured Plant:** Search for a species, link sensors, choose placement, and choose profile.
- **Edit Configured Plant:** Change sensors, placement, profile, or rain threshold. The form is pre-filled with the current values.
- **Remove Configured Plant:** Removes the selected plant.
- **Settings:** Change API credentials, enrichment toggles, update interval, forecast source, and ozone sensor.
- **Reset Plant Database:** Clears the species cache, learned baselines, and sample buffers.

Add, edit, and remove actions reload the integration automatically so entities appear, update, or disappear immediately.

## Data persistence

Everything that accumulates over time is anchored to persisted state, so a Home Assistant restart or outage does not reset the plant's history.

Persisted data includes:

- Rolling moisture, soil temperature, light, and PAR sample buffers.
- Learned baselines.
- Calibration progress.
- Dormancy day count.
- 90-day daily aggregate history.
- Long-running timers such as `days_dry`, `days_wet`, `days_cold`, and `days_warm`.

The long timers are stored as timestamps. Their duration is calculated from the stored start time, so they survive restarts, downtime, and sample-retention limits.

For example, if a plant has been dry for five days, it will still show five days after Home Assistant restarts.

## Known limitations

- **The first two weeks are calibration.** New plants show neutral states and a frozen Health score while baselines build. This is expected.
- **SMHI STRÅNG data is delayed.** STRÅNG publishes hourly data for complete calendar days, usually about a day behind.
- **Outdoor DLI uses the latest complete STRÅNG day.** This gives a stable daily light total, but it is not a live sunlight meter.
- **Indoor obstruction uses delayed outdoor data.** Because outdoor lux is delayed, obstruction detection compares indoor light with concurrent delayed outdoor data.
- **Migration from v3 may leave old entities.** Unique IDs changed in v4. Remove orphaned v3 entities manually under **Settings > Entities** if needed.
- **Air-quality support is limited to ozone.** The advisory is for outdoor plants only. It never changes health score or care action.

## Troubleshooting

| Symptom | Likely cause or fix |
|---|---|
| Health shows `calibrating` for days | Normal. The 14-day calibration is still running |
| Health never leaves `calibrating` after 2 weeks | A baseline could not be learned. Water the plant so a drying cycle can be observed |
| Sensor fault is on | Battery may be critical, or no usable linked sensor is available. Check the reason attribute |
| Outdoor light state is `unknown` | STRÅNG data is missing, or the STRÅNG API issue sensor is on |
| Moisture is always `dry_too_long` | The profile may be too strict, or the moisture sensor may be scaled wrong. Compare calculated moisture with the raw sensor |
| Nothing updates after adding a plant | The integration should reload automatically. If it does not, reload it manually |
| Recalibration is needed | Call `plant_helper.recalibrate` after repotting, soil changes, or moving the plant |
