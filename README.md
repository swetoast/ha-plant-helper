# Plant Helper

[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-Custom%20Integration-41BDF5?logo=home-assistant&logoColor=white)](https://www.home-assistant.io/)
[![HACS](https://img.shields.io/badge/HACS-Custom%20Repository-41BDF5)](https://hacs.xyz/)
[![Version](https://img.shields.io/badge/version-4.0.31-blue)](custom_components/plant_helper/manifest.json)

Plant Helper is a Home Assistant custom integration that turns local soil moisture, soil temperature, and light readings into calibrated, time-based plant-care guidance. It combines each plant's own learned behavior with optional STRÅNG solar radiation, weather forecasts, and read-only species context.

> **Release status:** Automated tests cover the decision engine, learning lifecycle, persistence logic, configuration contracts, and repository structure. The final live Home Assistant lifecycle checklist remains the release gate for v4.0.31.

## Highlights

- UI-based setup and plant management
- Per-placement 14-day calibration that extends when evidence is incomplete
- Independent indoor and outdoor learned baselines
- Conservative post-lock adaptation of the learned saturated-moisture peak
- Gap-aware telemetry validation that avoids learning across missing or invalid data
- Reboot-safe calibration, samples, condition timers, and daily history
- Direct SMHI STRÅNG support in Nordic coverage, with optional existing HA sensors
- Optional weather hazards, rain suppression, ozone advisory, and species context
- Health, care, moisture, light, temperature, calibration, species, and diagnostic entities

## Requirements

- A recent Home Assistant release
- One soil-moisture sensor per plant
- Optional soil-temperature, illuminance, and battery sensors
- Optional weather forecast source
- STRÅNG radiation through the direct SMHI API or existing Home Assistant sensors

## Installation

### HACS custom repository

Until Plant Helper is accepted into the default HACS catalogue:

1. Open **HACS**.
2. Select **Integrations**.
3. Open the menu and select **Custom repositories**.
4. Add `https://github.com/swetoast/ha-plant-helper` as an **Integration** repository.
5. Install **Plant Helper**.
6. Restart Home Assistant.
7. Open **Settings > Devices & services > Add integration** and select **Plant Helper**.

### Manual installation

1. Copy `custom_components/plant_helper` into your Home Assistant configuration directory.
2. Restart Home Assistant.
3. Open **Settings > Devices & services > Add integration**.
4. Select **Plant Helper**.

## Configuration

### Global settings

- **Forecast source:** optional weather entity or sensor carrying a forecast attribute
- **Ozone sensor:** optional outdoor ozone advisory source
- **Perenual API key:** optional species context
- **Trefle API token:** optional botanical context
- **iNaturalist enrichment:** optional keyless identity and photo context
- **Update interval:** default 300 seconds, accepted range 60–3600 seconds
- **Radiation source:** automatic, direct STRÅNG API, or existing STRÅNG sensors

### Per-plant settings

- **Plant name:** required display name and stable plant ID basis
- **Species:** optional read-only provider context
- **Soil moisture:** required percentage sensor
- **Soil temperature:** optional temperature compensation and thermal context
- **Light (lux):** optional indoor light adequacy and obstruction detection
- **Battery level:** optional numeric or categorical battery source
- **Placement:** indoor or outdoor
- **Care profile:** dry tolerant, balanced, moisture loving, or custom
- **Rain threshold:** optional outdoor rain-suppression threshold

## Calibration and learning

Each placement has its own learned model. A new placement begins a 14-day calibration, and calibration extends rather than locking if the required observations are incomplete. The Health sensor is unavailable while calibrating, and the separate **Calibration** diagnostic reports the learning state.

Plant Helper learns:

- saturated moisture peak
- dry threshold
- drying rate
- outdoor DLI target or indoor window transmission
- normal soil-temperature mean and daily swing

After lock, qualified higher moisture peaks may slowly adapt the learned maximum using a bounded EWMA. The dry threshold is regenerated from the stored standard or custom profile policy. Drying rate, DLI, window transmission, and thermal constants remain locked until dedicated bounded adaptation policies are implemented.

See [Learning lifecycle](docs/LEARNING_LIFECYCLE.md) for the twelve-stage ownership and verification map.

## Entities

Each plant exposes:

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

Hub-level entities report radiation-source and species-provider health.

The Species entity is context only. Provider data never overrides the calibrated care engine.

## Services

### `plant_helper.recalibrate`

Restarts calibration for one configured plant by clearing its learned model and local sample history. Species context remains separate.

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

## Removing the integration

1. Open **Settings > Devices & services**.
2. Open the Plant Helper integration menu.
3. Select **Delete**.
4. If installed through HACS, uninstall Plant Helper from HACS after deleting the integration entry.
5. Restart Home Assistant if requested.

Removing an individual plant from Plant Helper purges its device, entities, configuration, samples, learned state, timers, and history.

## Quality and verification

- [Quality roadmap](docs/QUALITY_ROADMAP.md)
- [Learning lifecycle and live-test checklist](docs/LEARNING_LIFECYCLE.md)
- [Build history](BUILD_PLAN.md)

For this revision, automated verification is complete for the pure engine and repository-level Home Assistant contracts. A real Home
Assistant test-load remains required to verify config-entry setup, options changes, entities, services, placement transitions, persistence, and clean reload/unload behavior before v4.0.31 is described as field-proven or field-verified.

## Support

Use [GitHub Issues](https://github.com/swetoast/ha-plant-helper/issues) for reproducible bugs and feature requests. Include the Plant Helper version, Home Assistant version, relevant diagnostics, and sanitized logs.

## License

See [LICENSE](LICENSE).
