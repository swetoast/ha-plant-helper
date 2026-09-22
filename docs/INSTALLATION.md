# Installation and configuration

## Install manually

1. Stop Home Assistant or prepare to restart it after copying the files.
2. Copy the complete `custom_components/plant_helper` directory to `<config>/custom_components/plant_helper`.
3. Confirm that `manifest.json` is directly inside that directory.
4. Restart Home Assistant.
5. Open **Settings > Devices & services > Add integration**.
6. Search for **Plant Helper** and complete setup.

Do not copy the repository root into `custom_components`. Only the `plant_helper` integration directory belongs there.

## Upgrade

1. Keep Home Assistant's `.storage` directory unchanged.
2. Replace the existing `custom_components/plant_helper` directory with the directory from the new release.
3. Restart Home Assistant.

Plant configuration is stored by Home Assistant and the integration storage layer. Replacing integration source files does not intentionally remove configured plants.

## Shared configuration

- **Latitude override** and **Longitude override**: optional coordinates. Leave both empty to use the Home Assistant location.
- **Outdoor ozone sensor**: optional Home Assistant sensor used for outdoor interpretation.
- **Perenual API key**: optional species-enrichment credential.
- **Perenual access level**: selects free or paid request behavior.
- **Trefle API token**: optional species-enrichment credential.
- **Update interval**: periodic local evaluation interval in seconds.

Shared settings can be changed with **Reconfigure** from the integration entry menu.

## Manage plants

Open the integration entry and select **Configure**.

- **Add plant** creates a plant with a display name, placement, optional species name, physical sensor mappings, and other available plant settings.
- **Edit plant** updates an existing plant while preserving its plant UUID and entity identity.
- **Remove plant** asks for confirmation before removing the plant's runtime state, entities, registry entries, device, and owned stored data.

Physical entity selectors may include soil moisture, soil temperature, humidity, illuminance, conductivity, battery, and outdoor ozone where supported by the flow. Battery accepts numeric percentage sensors and categorical soil-sensor battery-state entities.

## Optional species providers

Plant Helper can use Perenual, Trefle, and iNaturalist. Provider credentials are optional. Perenual free and paid access modes are handled separately. Provider failures are isolated from normal plant availability and local evaluation.

## Uninstall

1. Remove every plant through the Plant Helper options flow if the plant entities and devices should also be removed.
2. Remove the Plant Helper integration entry from Home Assistant.
3. Delete `custom_components/plant_helper`.
4. Restart Home Assistant.
