# 🌱 Plant Helper

A comprehensive Home Assistant custom integration for managing and monitoring your houseplants with local-first data caching and intelligent API usage.

[![Version](https://img.shields.io/badge/version-3.1.2-blue.svg)](https://github.com/swetoast/ha-plant-helper/releases)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.1+-blue.svg)](https://www.home-assistant.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz/)

## Why Plant Helper?

- **Works without dedicated sensors** - Calculates soil moisture using watering events and evaporation modeling
- **Local-first caching** - Downloads plant data once, uses it forever (no repeated API calls)
- **Smart API chain** - Local cache → Perenual → Trefle fallback → iNaturalist enrichment
- **Multi-provider merging** - Combines the best information from each data source
- **Guided setup flow** - Clear explanations at every configuration step

## Installation

### HACS (Recommended)

1. HACS → Three dots menu → Custom repositories
2. Add `https://github.com/swetoast/ha-plant-helper` as an Integration
3. Install "Plant Helper"
4. Restart Home Assistant
5. Settings → Devices & Services → Add Integration → "Plant Helper"

### Manual

1. Download the [latest release](https://github.com/swetoast/ha-plant-helper/releases)
2. Copy `custom_components/plant_helper/` to your Home Assistant config
3. Restart Home Assistant
4. Add the integration via UI

## Setup

### 1. Get API Keys

**Perenual** (required) - [perenual.com/docs/api](https://perenual.com/docs/api)
- Free tier: 100 requests/day
- Primary plant care database

**Trefle** (optional) - [trefle.io](https://trefle.io/)
- Free tier: 500 requests/day
- Fallback for plants Perenual doesn't have

### 2. Configure Integration

1. Add integration → Enter Perenual API key
2. Optional: Add Trefle API key
3. Enable features:
   - **Trefle fallback** - Backup plant database
   - **iNaturalist enrichment** - Extra photos and details (no key needed)

### 3. Add Plants

1. Integration options → "Add Configured Plant"
2. Search by common name (e.g., "Monstera", "Snake Plant")
3. Link your sensors (all optional):
   - Room temperature
   - Room humidity
   - Room light (lux)
   - Soil moisture (or let Plant Helper calculate it)

## Features

### Smart Plant Monitoring

**Calculated Soil Moisture** - No physical sensor needed
- Models evaporation based on temperature, humidity, and light
- Tracks watering events
- Uses real sensor if you add one later

**Created Sensors per Plant**
- Plant Status - Overall health with detailed attributes
- Soil Moisture - Percentage (0-100%)
- Light Score - Daily lux accumulation
- Temperature Stress - Time outside safe range
- Health Score - Overall wellness (0-100)
- Care Action - "Water soon", "Increase light", etc.

### Intelligent API Usage

Plant Helper searches in this order:
```
Local Database (instant)
    ↓ not found
Perenual API
    ↓ not found + fallback enabled
Trefle API
    ↓ optional
iNaturalist (photos/observations)
```

Once downloaded, plant data is cached locally. Future lookups are instant with zero API calls.

### Data Providers

**Perenual** - Watering schedule, sunlight needs, soil preferences, toxicity, growth rate, temperature ranges, care tips

**Trefle** - Scientific classification, pH ranges, humidity preferences, bloom periods, temperature limits

**iNaturalist** - Research-grade observations, community photos, regional distribution

## Configuration

### Plant Management

| Action | Purpose |
|--------|---------|
| Add Configured Plant | Create plant with sensors |
| Remove Configured Plant | Delete plant device |
| Fetch Species to Cache | Download data without creating sensors |
| View Plants | See monitored and cached plants |
| Reset Database | Clear all plant data |

### Settings

| Setting | Default | Description |
|---------|---------|-------------|
| Perenual API Key | Required | Primary plant database |
| Trefle API Token | Optional | Backup database |
| Trefle Fallback | Disabled | Search Trefle when Perenual fails |
| iNaturalist Enrichment | Disabled | Add photos and observations |
| Update Interval | 300s | Sensor refresh rate |

## Examples

### Dashboard Card

```yaml
type: entities
title: Monstera
entities:
  - entity: sensor.monstera_status
    secondary_info: last-changed
  - entity: sensor.monstera_health_score
  - entity: sensor.monstera_soil_moisture
  - entity: sensor.monstera_care_action
```

### Water Reminder

```yaml
automation:
  - alias: "Water Monstera"
    trigger:
      - platform: numeric_state
        entity_id: sensor.monstera_soil_moisture
        below: 30
    action:
      - service: notify.mobile_app
        data:
          message: "Monstera needs water ({{ states('sensor.monstera_soil_moisture') }}%)"
```

### Low Light Alert

```yaml
automation:
  - alias: "Monstera needs light"
    trigger:
      - platform: state
        entity_id: sensor.monstera_care_action
        to: "Increase light"
    action:
      - service: light.turn_on
        entity_id: light.grow_light
```

## API Limits & Best Practices

| Provider | Daily Limit | Between Requests |
|----------|-------------|------------------|
| Perenual | 100 | None |
| Trefle | 500 | 0.6s |
| iNaturalist | 300 | 1.0s |

**Save API calls:**
- Search once, add multiple plants using cached data
- Use "Fetch Species to Cache" to pre-download plants
- Enable Trefle fallback for better coverage
- Avoid force-fetch unless data is wrong

## Troubleshooting

**Plant not found?**
- Try variations: "Pothos" vs "Devil's Ivy"
- Enable Trefle fallback
- Check API Status binary sensor

**Sensors not updating?**
- Check linked sensors are working
- Verify update interval in settings
- Check Home Assistant logs

**Wrong plant data?**
- Integration options → "View Plants" → Check cached species
- If wrong: Remove from cache → Search again with better name

**Start fresh:**
- Integration options → "Reset Plant Database"
- Keeps API keys and settings
- Removes all plant data

## Contributing

Contributions welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for:
- Development setup
- Code guidelines
- How to add new providers
- Submitting PRs

## Credits

**Data Providers**
- [Perenual](https://perenual.com/) - Plant care database
- [Trefle](https://trefle.io/) - Botanical data
- [iNaturalist](https://www.inaturalist.org/) - Observations and photos

## License

MIT License - see [LICENSE](LICENSE)

## Disclaimer

Plant care data is guidance. Actual needs vary by plant age, pot size, soil, conditions, and season. Always observe your plants and adjust care accordingly.

---

Made with 🌱 for the Home Assistant community
