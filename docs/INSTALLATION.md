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
- Update interval - seconds between periodic local evaluations.

Ozone and forecast data come from Open-Meteo automatically for the configured
coordinates.

## Manage plants

Open the integration entry and select Configure:

- Add plant - name, placement, optional species, and physical sensor mappings.
- Edit plant - changes settings while keeping the plant's UUID and entities.
- Remove plant - confirms, then removes the plant's entities, device, registry
  entries, and stored data.

Sensor selectors cover soil moisture, soil temperature, humidity, illuminance,
and battery. Battery accepts a numeric percentage sensor or a categorical
soil-sensor battery-state entity.

## Species providers

Perenual, Trefle, and iNaturalist are all optional. Credentials are optional.
Provider failures are isolated: they never affect plant availability or local
evaluation.

## Uninstall

1. Remove each plant through Configure if you also want its entities and devices
   gone.
2. Delete the Plant Helper integration entry.
3. Delete `custom_components/plant_helper`.
4. Restart Home Assistant.
