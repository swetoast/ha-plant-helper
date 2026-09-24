# Entities

One device per plant. Unique IDs come from the config entry, the plant's
persistent UUID, and the entity key, so renaming a plant keeps its IDs.

Each plant has up to nine sensors and one binary sensor. An entity is
unavailable until it has usable data. Optional sensors (humidity, battery)
appear only when a source is configured.

## Status

`sensor.<plant>_status` - the care state, judged from moisture history rather
than a single reading:

- `normal`, `wet`, `drying` - within range or moving through it normally.
- `recently_watered` - moisture rose sharply; a watering was detected.
- `staying_wet`, `too_wet` - wet longer than expected. `too_wet` needs attention.
- `approaching_dry`, `needs_water`, `too_dry` - dry or drying past the range.
  `needs_water` and `too_dry` need attention.
- `watering_paused` - outdoor plant below range but rain is expected soon.
  Critically dry soil still recommends watering.
- `waiting_for_data` - no usable moisture reading yet.

Attributes:

- `summary`, `reason` - the verdict in plain language and as a machine key.
- `since` - when the current state began.
- `confidence` - `low` / `medium` / `high` data coverage. Escalations need at
  least medium.
- `drying_context` - `low` / `normal` / `high` expected drying speed.
- `dormant` - whether the plant is treated as seasonally dormant.
- `light_context`, `humidity_context` - `low` / `adequate` / `high`.
- `placement` - `indoor` or `outdoor`.
- Outdoor only: `rain_suppression`, `frost_hours`, `exposure`.
- Indoor only: `external_daylight`.

Attributes that do not apply to a plant are omitted.

## Health

`sensor.<plant>_health` - `good`, `watch`, `needs_water`, `too_wet`, `too_dry`,
or `unknown`. Moisture drives it. Sustained low or high light or humidity raises
it to `watch`, but only moisture raises needs-attention. Attribute: `summary`.

## Calibration

`sensor.<plant>_calibration` - `learning` while the plant builds its baseline,
`calibrated` once it is judged by its own learned moisture range. Calibration
takes roughly two weeks of readings. Attribute: `summary`.

## Moisture, Light, Temperature, Humidity

Current readings. Moisture and humidity in percent, light in lux, temperature
(soil) in degrees Celsius. Standard measurement device and state classes.

## Battery

`sensor.<plant>_battery` - the source battery level: `high`, `middle`, `low`, or
a number from 0 to 100. Categorical values are kept as-is, not converted.

## Species

`sensor.<plant>_species` - the resolved scientific name, or the query itself
when no confident match is found. Attributes: `scientific_name`, `common_name`,
`family`, `genus`, `watering_category`, `sunlight_requirements`, and `image_url`
(a local authenticated thumbnail). Provider names, raw responses, and
credentials are never exposed.

## Needs attention

`binary_sensor.<plant>_needs_attention` - problem device class. On only when the
plant needs action (dry, too wet, or too dry). Attribute: `reason`.

## Availability

- An entity without its own data is unavailable.
- Missing optional or provider data affects only that entity.
- A provider failure never takes the plant offline.
- Removing a plant removes its entities and device.
