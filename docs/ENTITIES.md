# Entities

One device per plant. Unique IDs come from the config entry, the plant's
persistent UUID, and the entity key, so renaming a plant keeps its IDs. The
device is named after the plant, its model is the species, and its software
version is the Plant Helper version. Renaming the plant renames the device.

Each plant has eleven sensors, one binary sensor, an image, a watering event and
a care profile select. Outdoor plants also get a rain limit number. An entity
without usable data (for example light, temperature, humidity, or battery when
no source is configured) stays unavailable.

Status, health, battery and the care profile have translated state names and
icons that follow the state. Battery and calibration are diagnostic entities;
the care profile and rain limit are configuration entities, so they appear
under Controls and Configuration on the device page rather than among the
sensors.

## Status

`sensor.<plant>_status` - the most useful current condition, judged from history
rather than a single reading. When several signals compete, the most urgent wins,
in this order:

- `sensor_problem` - the moisture sensor has reported nothing valid for six hours,
  or the device looks frozen (every reading exactly flat for five days).
- `needs_water`, `too_dry` - below the range; `too_dry` once it has lasted.
- `watering_paused` - outdoor plant below range but rain is expected soon.
  Critically dry soil still recommends watering.
- `too_wet`, `staying_wet` - wet far longer than the conditions explain.
- `recently_watered` - moisture rose sharply; a watering was detected.
- `partial_watering` - the last watering peaked well short of what this pot
  normally reaches (needs a learned baseline).
- `drying`, `approaching_dry` - falling normally, or nearing the dry threshold.
- `too_cold`, `too_hot` - a sustained or extreme temperature condition.
- `insufficient_light` - three low-light days in a row, or two bright days
  outside while this spot stayed dim (likely shaded).
- `wet`, `normal` - elevated after watering, or within range.
- `waiting_for_data` - no usable moisture reading yet.

Attributes:

- `summary`, `reason` - the verdict in plain language and as a machine key.
- `since` - when the current condition began.
- `confidence` - `low` / `medium` / `high` data coverage. Escalations need at
  least medium.
- `drying_context` - `low` / `normal` / `high` expected drying speed.
- `light_context` - `low` or `adequate`, from the last completed day.
- `humidity_context`, `temperature_context` - `low` / `adequate` / `high`.
- `dormant` - whether the plant is treated as seasonally dormant; calm statuses
  then carry reason `seasonal_dormancy`.
- `placement` - `indoor` or `outdoor`.
- Outdoor only: `rain_suppression`, `frost_hours`, `exposure`.
- Indoor only: `external_daylight`.

Attributes that do not apply to a plant are omitted.

## Health

`sensor.<plant>_health` - the longer-term verdict: `good`, `watch`, `stressed`,
or `unknown`. It does not mirror every temporary condition: a single reading, a
brief cold spell, or one overcast day leaves it `good`.

- `watch` - a developing concern: soil staying wet or below range, a prolonged
  temperature or humidity excursion, insufficient light, a grow light the plant
  normally gets going missing, or soil drying much slower than this plant
  normally does.
- `stressed` - sustained harm: prolonged dryness, a prolonged extreme
  temperature, or persistently wet soil in cold conditions.
- `unknown` - no usable moisture data, or a sensor problem.

Attribute: `summary`, describing whatever set the verdict.

## Calibration

`sensor.<plant>_calibration` - diagnostic. How far the plant is towards its own
learned moisture range, in percent: 100 once calibrated. Half of the progress is
days of readings (14 needed), half is complete watering cycles (2 needed); it
stays at 99 until the readings are steady and the swing between waterings is
wide enough to learn from. Until then the plant is judged by its care profile.

Attributes:

- `phase` - `learning` or `calibrated`. Automations that tested the old
  `learning`/`calibrated` state should test this attribute.
- `days`, `days_required`, `cycles`, `cycles_required` - the two gates.
- `waiting_for` - what calibration still needs, in plain language, for example
  "one more complete watering cycle".
- `estimated_ready` - the local date calibration should finish, from the usual
  time between waterings. Absent until a watering interval is known.
- `learned_norms` - which of `light`, `temperature`, `humidity` have a learned
  normal.
- `learned_low`, `learned_high` - the learned moisture range, once calibrated.
- `summary` - the above in one sentence.

To start over, use the `plant_helper.relearn` action (see SERVICES.md).

Learning continues afterwards: the typical
watering rise and peak, drying speed, time back to range, normal light,
temperature and humidity, and month-to-month variation keep refining. Learned
values stay within reach of the selected care profile, readings taken while the
plant is waterlogged, parched, or faulty are not learned, and indoor and outdoor
baselines are kept separately. Attribute: `summary`.

## How signals are judged over time

- Moisture: watering cycles. A watering is a rise, within six hours, larger than
  the probe's own noise (1.5 times its typical daily range, between 5 and 20
  points), so a sensor's day/night swing is never mistaken for watering. A slow
  soak counts as one watering until the soil dries back again. Soil counts as
  drying when it falls about a point a day or more over the last two days, which
  averages out the daily swing. A band edge only clears 2 points back inside, so
  a sensor wobbling on the edge does not flicker the status. How long wet soil is
  tolerated starts from this pot's learned time back to range and scales with
  expected drying (soil trend, temperature, air dryness as vapor pressure
  deficit, light, and outdoor radiation), from 35% shorter to twice as long, and
  up to three times as long while dormant. A dry spell raises attention only
  after 30 minutes.
- Temperature and humidity: continuous time out of range, total time out of range
  in the last 24 hours, and recovery time. Brief excursions change the summary,
  not health. Indoor air counts as humid above 80% (very humid above 90%). The
  plant's learned normal range widens the mild bands, never the extremes.
- Light: cumulative lux-hours during daylight, bounded by sunrise and sunset from
  Open-Meteo, a cached forecast, or Home Assistant's own sun position. Night does
  not count against a plant. A day is low below 2500 lx-h, relaxed to half of
  this plant's own normal for the month once learned (never below 1000 lx-h), so
  a darker season does not keep a healthy plant flagged. A plant that normally
  gets a grow light is flagged when two nights pass without one. Light at night
  counts as supplemental only after 15 continuous minutes, at 60% weight, and
  belongs to the day the session started.
  Overcast days are forgiven for up to three days. When the daylight window is
  unknown, no light alert can fire.
- Dormancy: at least two weeks of low light within the last month plus a
  slightly cooler recent week or a cool room (or an outdoor plant outside its
  growing season). Dormant plants tolerate wet soil
  longer and are prompted to water at a lower moisture level.

## Moisture, Light, Temperature, Humidity

Current readings from the configured sources. Moisture and humidity in percent,
light in lux, temperature in degrees Celsius, with the standard measurement
device and state classes. Shown with whole numbers, temperature with one
decimal; change it per entity in its settings.

## Battery

`sensor.<plant>_battery` - diagnostic. The source battery level: a percentage
with the battery device class and Home Assistant's level icons, or, for sensors
that only report a category, an enum of `low`, `middle`, `high` (shown as Low,
Medium, High). Categorical values are kept as-is, not converted.

## Last watered

`sensor.<plant>_last_watered` - timestamp of the last detected watering. A slow
soak counts once. Survives restarts.

## Watering event

`event.<plant>_watering` - fires event type `watered` (attribute `watered_at`)
each time a new watering is detected. Restoring the stored last watering after a
restart does not fire it. Use it as an automation trigger or to see waterings
in the logbook.

## Daily light

`sensor.<plant>_daily_light` - yesterday's effective light in lux-hours:
natural daylight plus supplemental light at 60% weight, as used
for the light verdict. Yesterday is the last complete day, so the value does not
drop to zero at midnight. Attributes: `day`, `natural`, `supplemental`,
`classification` (for example `normal`, `low_light`, `overcast_day`), and
`today_so_far` (rounded to 100 lx-h). Unknown without a light sensor.

## Species

`sensor.<plant>_species` - the scientific name of the species you chose when
adding or re-matching the plant (Trefle's accepted name when a Trefle record was
chosen). Plants added before per-provider matching show the name found by the
older name-based lookup until they are re-matched. Each attribute comes from the
provider records you picked:

- Any provider: `scientific_name`, `common_name`, `family`, `genus`, and
  `image_url` (a local authenticated thumbnail).
- Trefle, when it has them: `light_requirement`, `humidity_requirement`,
  `soil_moisture_requirement` (0-10 scales), `ph_minimum`, `ph_maximum`,
  `minimum_temperature_c`, `maximum_temperature_c`, `growth_habit`,
  `growth_rate`, `toxicity`, `average_height_cm`, `duration`, and `edible`.
- Perenual: `watering_category`, `watering_interval` (for example "every 5-7
  days"), `sunlight_requirements`, `care_level`, `growth_rate` (when Trefle has
  none), `indoor`, `drought_tolerant`, `poisonous_to_pets`, and
  `poisonous_to_humans`.

Fields a provider does not have for a species are simply absent. Provider
names, raw responses, and credentials are never exposed.

`image.<plant>` - the species photo, when one was found. Served from the local
WebP cache through Home Assistant's own image proxy, so it renders natively as
the entity picture. Unavailable until a photo has been fetched. It is the same
cached image linked from the `image_url` attribute above.

## Needs attention

`binary_sensor.<plant>_needs_attention` - problem device class. On only for
sustained, actionable conditions. Attribute `reason`: `soil_dry`,
`persistently_dry`, `persistently_wet`, `prolonged_temperature_stress`,
`several_days_insufficient_light`, or `sensor_problem`. It stays off for
recently watered, wet, or drying soil, one overcast day, a brief cool period,
or a short humidity excursion.

## Care profile and rain limit

`select.<plant>_care_profile` - configuration. `dry`, `balanced`, `moist` or
`custom`; changing it saves the plant exactly like Edit a plant. `custom` needs
a custom multiplier, which is only set in Edit a plant.

`number.<plant>_rain_limit` - configuration, outdoor plants only. Forecast rain
in mm at or above which watering is paused (0 to 1000). The entity is removed
when the plant is moved indoors.

## Availability

- An entity without its own data is unavailable.
- Missing optional or provider data affects only that entity.
- A provider failure never takes the plant offline.
- Removing a plant removes its entities and device.
