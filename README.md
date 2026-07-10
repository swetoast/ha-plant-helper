# Plant Helper

A Home Assistant custom integration that turns local soil, temperature and light
sensors — augmented by regional solar-irradiance data and a weather forecast —
into **calibrated, time-based plant-care guidance**.

Unlike threshold-based plant cards, Plant Helper does not judge a plant from an
instantaneous reading. It learns each plant's normal behaviour over a two-week
calibration, then describes measured growing conditions **over time**: how much
light was actually accumulated today, how long the soil has really been dry, how
the room compares to the plant's learned baseline, and whether the plant has
entered seasonal dormancy.

---

## Table of contents

1. [How it works (the short version)](#how-it-works-the-short-version)
2. [Requirements](#requirements)
3. [Installation](#installation)
4. [Configuration](#configuration)
5. [The 14-day calibration](#the-14-day-calibration)
6. [The sensors](#the-sensors) ← *what each entity means and how to use it*
7. [Care profiles & placement](#care-profiles--placement)
8. [Services](#services)
9. [Managing plants (add / edit / remove)](#managing-plants-add--edit--remove)
10. [Data persistence](#data-persistence)
11. [Known limitations](#known-limitations)
12. [Troubleshooting](#troubleshooting)

---

## How it works (the short version)

Every ~10 minutes the integration:

1. Reads each plant's local sensors (soil moisture, soil temperature, light) plus
   shared macro data (SMHI STRÅNG irradiance, sun elevation) and a weather
   forecast.
2. Stores those readings in a rolling buffer that **survives restarts**.
3. Runs a decision engine that produces, per plant: a **moisture** state, a
   **light** state, a **temperature** state, a **dormancy** flag, an overall
   **health** score, and a single prioritised **care action**.

The engine is built from independent models (moisture, light, thermal, dormancy,
health) and a precedence ladder that collapses them into one recommendation, so
you never get contradictory advice.

---

## Requirements

| Requirement | Why | Required? |
|---|---|---|
| Home Assistant (recent release) | Host | Yes |
| Per-plant **soil moisture** sensor | Primary care signal | Strongly recommended |
| Per-plant **soil temperature** sensor | Drives moisture compensation & thermal state | Recommended |
| Per-plant **light (lux)** sensor | Indoor light adequacy & obstruction | Recommended (indoor) |
| Per-plant **battery** sensor | Halts care logic on critical battery. Accepts a percentage **or** a categorical state (high / middle / low) | Optional |
| **SMHI STRÅNG** integration | Outdoor DLI (light integral) + cloud dynamics | Required for outdoor plants |
| A **weather** entity or forecast sensor | Rain suppression + severe-weather hazard | Optional but recommended |

The engine itself is pure Python (standard library only) — no extra
`requirements` are installed.

---

## Installation

1. Copy the `plant_helper` folder into `config/custom_components/`.
2. Restart Home Assistant.
3. **Settings → Devices & Services → Add Integration → Plant Helper.**
4. Complete initial setup (API keys are optional; see below), then add plants
   from the integration's **Configure** (options) screen.

---

## Configuration

### Global settings (Configure → Settings)

| Field | Purpose |
|---|---|
| Perenual API key | Optional — species enrichment (common name, tips, facts) |
| Trefle API token | Optional — enrichment fallback |
| Enable Trefle fallback / iNaturalist enrichment | Toggle context providers |
| Update interval | Poll cadence in seconds (default 600) |
| Forecast source | A `weather.*` entity **or** a `sensor.*` that exposes a `forecast` attribute (e.g. a combined hourly-weather sensor) |
| Ozone sensor (optional) | A `sensor.*` reporting ground-level ozone in µg/m³ (e.g. an AQI integration). Enables the outdoor **Ozone advisory** |

> Enrichment providers add **context only** (names, tips, photos). They never
> drive care decisions — those come from the learned per-plant baseline.

### SMHI STRÅNG sensors

The macro layer defaults to the standard STRÅNG entity IDs
(`sensor.smhi_strang_par`, `..._global_irradiance`, `..._diffuse_irradiance`,
`..._direct_horizontal_irradiance`, `..._outdoor_lux`) and the
`binary_sensor.smhi_strang_api_issue` health sensor. No configuration is needed
if you use the standard names.

### Per-plant configuration

When you add a plant you link its sensors and choose:

| Field | Notes |
|---|---|
| Soil temperature / soil moisture / room temperature / room humidity / light (lux) | Link your entities |
| Battery level | Optional; critical battery pauses care |
| **Placement** | `indoor` or `outdoor` — selects the light model (see below) |
| **Care profile** | `dry_tolerant`, `balanced`, `moisture_loving`, or `custom` |
| **Rain suppression threshold (mm)** | Outdoor only — forecast rain above this downgrades a dry alert |

**Sensor compatibility notes**

- **Soil moisture:** any `sensor` works whether its device class is `humidity`
  (older HA / most BLE soil probes) or `moisture` (newer HA). It is always
  presented as *moisture*, regardless of what the source sensor calls it.
- **Battery:** works with a numeric percentage **or** a categorical state
  (`high` / `middle` / `low`). `low` (or empty/critical) halts care; an
  unreadable battery never falsely halts care. The reading is shown on the
  **Sensor fault** binary sensor (`battery_level` / `battery_percent`).
- **Light (lux):** any `illuminance` sensor; it can be a repurposed room sensor
  placed at the plant.

---

## The 14-day calibration

When a plant is first added (or after **Recalibrate**), it enters a **14-day
observation phase**. During this time it learns, per plant:

- `M_max` — the saturated moisture peak (rolling 3-hour average).
- `M_dry` — the dry threshold (`profile multiplier × M_max`).
- The average daily drying rate.
- `DLI target` (outdoor) — the baseline daily light integral.
- `K_window` (indoor) — how much outdoor light your window actually passes, **per
  sun-elevation band** (so it stays valid across seasons).
- The expected temperature mean and normal day–night swing.

**During calibration:**
- Care alerts are suppressed.
- The **Health** sensor reads `calibrating` (no score) — this is expected, not a
  fault.
- If, by day 14, a required baseline still can't be trusted (e.g. you never
  watered, so no drying curve was seen), calibration **extends** rather than
  locking a bad baseline.

---

## The sensors

Each plant becomes a **device** with the sensors below. All are thin readers of
the engine — no logic lives in the entities.

### Sensor entities

| Sensor | State | Key attributes | How to use it |
|---|---|---|---|
| **Health** | `0–100` (or `calibrating`) | `health_state`, `components`, `primary_issue`, `reason`, `dormant`, `run_days` | Your at-a-glance number. `health_state` is `excellent/good/fair/poor/critical`. Frozen during calibration and floored during dormancy. |
| **Care action** | e.g. `water_now` | `primary_issue`, `reason`, `severity` | The **single** thing to do right now. `severity` (0–100) is good for sorting/automations. |
| **Moisture** | moisture state | `calculated_moisture`, `days_until_dry`, `days_since_watered`, `watering_urgency`, `suppressed_by_rain`, **`days_dry`**, **`days_wet`** | Watering guidance. `days_dry`/`days_wet` are reboot-safe counters (see [persistence](#data-persistence)). |
| **Light** | light state | `light_score`, `adequacy_ratio`, `obstruction`, `source`, `light_hours_today`, `daylight_hours` | Light adequacy. `source` is `dli` (outdoor) or `window` (indoor). `obstruction=true` means the window is being blocked. |
| **Temperature** | thermal state | `drying_modifier`, `hazard`, `hazard_type`, **`days_cold`**, **`days_warm`** | Thermal comfort + explains moisture behaviour (`drying_modifier` < 1 = cloudy/slower drying). |
| **Calibration** *(diagnostic)* | `calibrating` / `active` | — | Whether the plant is still learning or fully active. |
| **Species** | common name | `care_level`, `watering`, `sunlight`, `cycle`, `drought_tolerant`, `poisonous_to_pets`/`_humans`, `suggested_profile`, `reference_watering_days`, botanical prefs; photo shown as the entity picture | Context from Perenual/Trefle/iNaturalist — reference only, never affects care. Compare `reference_watering_days` with Moisture's `days_until_dry`. |

### Binary sensors

| Binary sensor | Device class | On when | How to use it |
|---|---|---|---|
| **Needs water** | problem | care action is `water_now` or `water_soon` | Simplest "water me" automation trigger. |
| **Weather hazard** | safety | severe weather imminent (outdoor) | Fire a "bring the plant in / shelter it" notification. |
| **Sensor fault** *(diagnostic)* | problem | care halted (critical battery or no usable sensors) | Alerts you the readings — not the plant — are the problem. Attributes `reason`, `battery_level`, `battery_percent`. |
| **Light obstruction** | problem | window blocked (indoor) | "Open the blinds" reminder. |
| **Dormant** | — | plant in seasonal dormancy | Informational; care is intentionally relaxed. |
| **Ozone advisory** *(outdoor, optional)* | problem | ground-level ozone is elevated/high | Advisory only — sensitive foliage may stress. Attributes: `advisory`, `ozone_ugm3`, `message`. Created only when an ozone sensor is configured and the plant is outdoor. |

### State reference

**Moisture states:** `recently_watered`, `drying_normally`, `getting_dry`,
`dry_too_long`, `wet_too_long`, `normal`, `suppressed_by_rain`.

**Light states:** `normal`, `higher_daily_light`, `lower_daily_light`,
`lower_3d`, `lower_this_week`, `recovering`, `unknown`.

**Temperature states:** `stable`, `cooler_than_usual`, `warmer_than_usual`,
`cold_too_long`, `warm_too_long`, `swingy`, `weather_hazard_imminent`, `unknown`.

**Care actions:** `water_now`, `water_soon`, `reduce_water`, `seek_shelter`,
`move_warmer`, `move_cooler`, `clear_obstruction`, `increase_light`,
`check_sensor`, `monitor`, `none`.

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

---

## Care profiles & placement

**Profiles** set how strict the moisture rules are (via the `M_dry` multiplier):

| Profile | `M_dry` | Good for |
|---|---|---|
| `dry_tolerant` | 0.25 × M_max | Cacti, succulents, snake plants |
| `balanced` | 0.50 × M_max | Most houseplants |
| `moisture_loving` | 0.70 × M_max | Ferns, calatheas, tropicals |
| `custom` | your multiplier | Fine-tuning |

**Placement** switches the light model:
- **Indoor** → the *Window Efficiency Ratio*. Distinguishes a genuinely dim day
  (indoor and outdoor light drop together → `normal`) from an **obstruction**
  (outdoor bright, indoor dark → `lower_daily_light` + obstruction flag).
- **Outdoor** → true **Daily Light Integral** from SMHI PAR, compared to the
  learned target, with 3-day / 7-day shortfall detection.

A plant that summers outside and winters inside keeps **separate baselines per
placement** — switching placement swaps to the stored baseline instead of forcing
a fresh calibration (unless that placement was never calibrated).

---

## Services

### `plant_helper.recalibrate`

Wipes a plant's learned baseline and sample history to restart the 14-day
calibration. **Use after repotting, changing soil composition, or moving the
plant to a different room / between indoor and outdoor.**

```yaml
service: plant_helper.recalibrate
data:
  plant_id: monstera_livingroom
```

---

## Managing plants (add / edit / remove)

All plant management is under **Settings → Devices & Services → Plant Helper →
Configure**:

- **Add Configured Plant** — search a species (for enrichment), link sensors,
  choose placement/profile.
- **Edit Configured Plant** — change a plant's sensors, placement, profile, or
  rain threshold. The form is pre-filled with the current values.
- **Remove Configured Plant** — removes the plant.
- **Settings** — API credentials, enrichment toggles, update interval, forecast
  source.
- **Reset Plant Database** — clears the species cache **and** the learned
  baselines / sample buffers.

Add / edit / remove automatically reload the integration so entities appear,
update, or disappear immediately.

---

## Data persistence

Everything that accumulates over time is anchored to persisted state, so a Home
Assistant **restart or an outage does not restart the clock**:

- **Rolling sample buffers** (moisture/soil-temp/light/PAR) survive reboots, so
  the 24-hour / 3-day / 7-day windows resume where they left off.
- **Learned baselines, calibration progress, dormancy day-count, and the
  90-day daily-aggregate history** persist in a versioned store with a migration
  hook.
- **The long "too-long" timers** (`days_dry`, `days_wet`, `days_cold`,
  `days_warm`) are stored as "since" timestamps, so their duration is computed as
  *now − since*. This makes them immune to both sample-retention limits and
  downtime — a plant that has been dry for five days still reads five days after
  a reboot or a day of HA being offline.

---

## Known limitations

- **First two weeks are calibration.** New plants show neutral states and a
  frozen Health score for ~14 days while baselines build. This is by design.
- **SMHI STRÅNG lags ~a day and is delivered per calendar day.** STRÅNG
  publishes hourly data for a full calendar day, ~a day behind. Outdoor **DLI is
  the integral of the most recent *complete* STRÅNG day** — a true per-day light
  integral that is stable across local midnight (a just-started day is skipped
  until it completes). Fine for a slowly-changing plant; not a live sunlight
  meter.
- **Indoor obstruction is lag-paired.** Because outdoor lux is lagged, indoor
  obstruction is evaluated against concurrent-but-delayed outdoor data.
- **Migration from v3.** Entity unique IDs changed in v4. After upgrading you may
  see orphaned v3 entities in **Settings → Entities**; remove them manually.
- **Air-quality advisory** is limited to ground-level **ozone** (the one
  pollutant with real plant relevance), outdoor plants only, and is **advisory
  only** — it never changes the care action or health score. SO₂ and
  particulates are intentionally excluded (negligible at ambient levels). The
  ozone thresholds are instantaneous proxies, not the cumulative AOT40 metric.

---

## Species enrichment & API diagnostics

If you provide a species name (and optionally a Perenual API key), Plant Helper
fetches species context once a day from **Perenual**, **Trefle**, and
**iNaturalist** and surfaces it on the **Species** sensor: common/scientific
name, care level, watering guidance, sunlight, toxicity to pets/humans, a
suggested care profile, a reference watering interval, botanical preferences, and
a photo. This is **context only** — the calibrated engine still makes every care
decision.

Each provider gets a hub-level **API diagnostic** binary sensor (Perenual API,
Trefle API, iNaturalist API), grouped under Diagnostics, showing `last_success`,
`last_error`, `calls_today`, `daily_limit`, and `enabled` — mirroring the SMHI
STRÅNG / AccuWeather API-issue sensors.

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Health shows `calibrating` for days | Normal — 14-day calibration in progress. |
| Health never leaves `calibrating` after 2 weeks | A baseline couldn't be learned (e.g. never watered → no drying curve). Water the plant so a drying cycle is observed. |
| **Sensor fault** on | Critical battery, or no usable linked sensor. Check the `reason` attribute. |
| Light state `unknown` (outdoor) | STRÅNG data missing or the API-issue sensor is on. |
| Moisture always `dry_too_long` | Wrong profile (too strict) or a mis-scaled moisture sensor. Check `calculated_moisture` vs your raw sensor. |
| Nothing updates after adding a plant | The integration should auto-reload; if not, reload it manually. |
| Recalibration needed | Repotted / moved the plant → call `plant_helper.recalibrate`. |
