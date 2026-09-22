# Plant Helper

Plant Helper is a Home Assistant custom integration for monitoring indoor and outdoor plants. It combines configured physical sensors with placement, weather, air-quality, learning, and optional species information to produce a compact set of useful plant entities.

## Features

- One Home Assistant device per plant.
- Status, moisture, light, temperature, health, calibration, and species sensors.
- A problem binary sensor for plants that need attention.
- Indoor and outdoor placement behavior.
- Event-driven physical sensor updates.
- Optional species enrichment through Perenual, Trefle, and iNaturalist.
- Secure, authenticated species-image thumbnails.
- Dynamic add, edit, and remove flows without manually editing YAML.
- Minimal entity attributes without provider or debug clutter.

## Requirements

- Home Assistant with support for config-entry based custom integrations.
- Physical Home Assistant sensor entities are optional, but provide the most useful measurements.
- Internet access is optional. It is used only by configured forecast, air-quality, species, or image features.
- Perenual and Trefle credentials are optional.

## Installation

1. Copy `custom_components/plant_helper` into the `custom_components` directory in the Home Assistant configuration directory.
2. Restart Home Assistant.
3. Open **Settings > Devices & services**.
4. Select **Add integration** and search for **Plant Helper**.
5. Complete the shared configuration form.
6. Open the integration's **Configure** menu to add the first plant.

See [Installation and configuration](docs/INSTALLATION.md) for upgrades, configuration fields, and plant management.

## Entities

Humidity and battery source values are exposed when configured. Battery preserves either `high`, `middle`, or `low`, or a numeric value from 0 through 100. Calibration reports `source_sensor` to confirm that Plant Helper uses the selected sensor reading and does not require a separate Plant Helper calibration step.


Each plant can expose seven sensors and one binary sensor. Entities remain unavailable until data for that specific entity exists. Missing optional data does not make unrelated plant entities unavailable.

See [Entity reference](docs/ENTITIES.md).

## Actions and services

Plant management is performed through the integration configuration and options flows. This release does not register Home Assistant service actions. See [Actions and services](docs/SERVICES.md).

## Species data and images

Species providers are optional. Provider failures do not make the plant unavailable. Accepted images are downloaded only over HTTPS, validated, converted to static WebP thumbnails, stored by content hash, and served through an authenticated Home Assistant endpoint.

## Troubleshooting

See [Troubleshooting](docs/TROUBLESHOOTING.md) for installation, unavailable entity, provider, image, and plant-removal guidance.

## Development verification

The release source includes automated tests for configuration flows, storage, concurrency, runtime lifecycle, physical events, learning, placement, forecast, air quality, species enrichment, image security, entity contracts, registry behavior, privacy, translations, and packaging.

## License

No license file is included in this release. Distribution and reuse terms must be defined by the project owner before public distribution.

## HACS installation

The repository metadata is configured for `https://github.com/swetoast/ha-plant-helper`.

After the repository is published:

1. Open HACS.
2. Open **Integrations**.
3. Add the GitHub repository as a custom repository with category **Integration**.
4. Select **Plant Helper** and install it.
5. Restart Home Assistant.
6. Add Plant Helper from **Settings > Devices & services**.

## Maintenance

See the [post-release maintenance plan](docs/POST_RELEASE_MAINTENANCE.md) for release policy, compatibility checks, provider maintenance, security priorities, and the release checklist.
