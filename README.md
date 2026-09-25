# Plant Helper

A Home Assistant integration that watches your plants and says what they need in
plain language. One device per plant. It reads your existing soil, light,
humidity, and temperature sensors and turns them into a small set of useful
entities.

Moisture is judged from recent history, not a single reading, so a brief spike
no longer trips a false alarm. Each plant learns its own normal range over time,
outdoor plants factor in the weather, and dormant plants are left alone about
wet soil instead of being nagged.

## What it does

- One device per plant: status, moisture, light, soil temperature, humidity,
  battery, health, calibration, and species sensors, plus a needs-attention
  binary sensor.
- Trend-based moisture care. Watering, drying, too wet, and too dry are read
  from the recent history, with a confidence gate so sparse data never drives an
  alarm.
- Per-plant learning. A plant learns its comfortable moisture band from its own
  watering cycles and is then judged against that instead of a generic profile.
- Light judged as cumulative daylight exposure, bounded by sunrise and sunset,
  with grow lights counted separately and overcast days forgiven; night never
  counts against a plant.
- Temperature and humidity judged by how long they stay out of range, not by a
  single reading, and combined with moisture (cold and wet, warm and dry).
- Seasonal dormancy detected from a month of light and temperature history.
- Weather aware, outdoor. Rain pauses a watering recommendation, frost and
  exposure show as context, and dormant plants tolerate wet soil longer.
- Optional species enrichment from iNaturalist, Trefle, and Perenual. You pick
  the right record from each provider (or skip it) when adding a plant, and can
  re-match later; each chosen record is then fetched by ID and cached, with a
  local, authenticated species photo.
- Add, edit, and remove plants from the UI. No YAML.

## Requirements

- Home Assistant with config-entry custom integrations.
- Physical sensor entities are optional but give the most useful readings.
- Internet is optional. It powers the Open-Meteo forecast and air quality and
  the optional species providers. Without it, plants run on physical sensors
  alone.
- Perenual and Trefle credentials are optional.

## Install

1. Copy `custom_components/plant_helper` into `<config>/custom_components`.
2. Restart Home Assistant.
3. Settings > Devices & services > Add integration, search for Plant Helper.
4. Complete the shared form, then open Configure to add your first plant.

Upgrades and configuration fields: [Installation](docs/INSTALLATION.md).

## Entities

Each plant exposes up to nine sensors, one binary sensor, and one image entity. An entity stays
unavailable until it has data; missing optional data does not affect the rest.
Full reference: [Entities](docs/ENTITIES.md).

## Species data and photos

Providers are optional and isolated: a provider failure never takes a plant
offline. Once iNaturalist confirms a match, Trefle is queried for taxonomy and
then for its growth/care record (light, humidity, soil-moisture, pH and
temperature ranges, toxicity, height, duration and more), self-regulating
against Trefle's published rate limit so it backs off before exhausting the
window rather than absorbing 429s. Species photos are downloaded server-side, validated, converted to
WebP, cached, and served from an authenticated local endpoint, so the frontend
never loads a raw provider URL. The photo is exposed as `image.<plant>`, which
Home Assistant renders natively as the entity picture, and is also linked from
the species sensor's `image_url` attribute for use in custom cards.

## More

- [Actions and services](docs/SERVICES.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Maintenance](docs/POST_RELEASE_MAINTENANCE.md)

## HACS

Repository: `https://github.com/swetoast/ha-plant-helper`. Add it in HACS as a
custom repository with category Integration, install, restart, then add Plant
Helper from Settings > Devices & services.

## License

Released under the MIT License. See [LICENSE](LICENSE) for the full text.
