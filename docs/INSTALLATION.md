# Installation and configuration

## Install

1. Copy the `custom_components/plant_helper` directory to
   `<config>/custom_components/plant_helper`. Copy the integration directory
   itself, not the repository root.
2. Confirm `manifest.json` sits directly inside it.
3. Restart Home Assistant.
4. Settings > Devices & services > Add integration, search for Plant Helper, and
   complete setup.

## Upgrade

Replace `custom_components/plant_helper` with the new release and restart. Leave
`.storage` alone; your plants and learned data live there and are preserved.

## Shared settings

Set once during setup, changed later with Reconfigure on the integration entry:

- Latitude / Longitude override - optional. Leave empty to use the Home
  Assistant location.
- Perenual API key and plan - optional species-enrichment credential. Set the
  plan to free unless the key is on Premium or Supreme: on free, only the
  records the key can open (IDs up to 3000) are offered when matching.
- Trefle API token - optional species-enrichment credential.
- Weather refresh interval - seconds between Open-Meteo refreshes (default
  300). Plants are evaluated every minute and on every sensor change regardless.

Forecast data (including sunrise and sunset for light accounting) comes from
Open-Meteo automatically for the configured coordinates, plus air quality
(ozone) for outdoor plants.

## Manage plants

Open the integration entry and select Configure:

- Add a plant - placement, then name, care profile, and physical sensor
  mappings, then one step per configured species provider (iNaturalist, Trefle,
  Perenual) to pick the matching record or skip it.
- Edit a plant - changes settings while keeping the plant's UUID, entities,
  learned data, and chosen species records.
- Re-match species data - redo or skip any provider's record for a plant,
  optionally searching for a different name.
- Remove a plant - confirms, then removes the plant's entities, device,
  registry entries, and stored data.

Sensor selectors cover soil moisture (required), soil temperature, air
humidity, light, and battery. Battery accepts a numeric percentage sensor or a
categorical soil-sensor battery-state entity (`low`, `middle`, `high`).

Care profiles set the moisture range a plant is judged against until it has
learned its own: dry 15-45%, balanced 25-65%, moist 40-80%. `custom` currently
uses the balanced range; its multiplier is stored but not yet applied. Outdoor
plants also take a rain threshold: rain forecast for the next six hours at or
above it pauses a watering recommendation.

## Species providers

iNaturalist needs no key; Trefle and Perenual need their own. Each provider
you configure gets a step when adding or re-matching a plant, and every step can
be skipped. Chosen records are cached for six months, so restarts do not spend
provider quota. Provider failures are isolated: they never affect plant
availability or local evaluation. See [Troubleshooting](TROUBLESHOOTING.md) for
what each provider can and cannot supply.

## Uninstall

1. Remove each plant through Configure if you also want its entities and devices
   gone.
2. Delete the Plant Helper integration entry.
3. Delete `custom_components/plant_helper`.
4. Restart Home Assistant.
