# 🌱 Plant Helper

A comprehensive Home Assistant custom integration for managing and monitoring your houseplants with local-first data caching and intelligent API usage.

[![Version](https://img.shields.io/badge/version-3.1.2-blue.svg)](https://github.com/swetoast/ha-plant-helper/releases)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.1+-blue.svg)](https://www.home-assistant.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz/)

## Features

- 🗄️ **Local-First Database** - Cached plant data is reused before any external API calls
- 🌍 **Multi-Provider Support** - Perenual (primary), Trefle (fallback), iNaturalist (enrichment)
- 📊 **Smart Sensors** - Calculated soil moisture, light tracking, health scores, and care recommendations
- 🔗 **Sensor Linking** - Connect your existing temperature, humidity, and light sensors
- 📉 **Rate Limiting** - Built-in API quota management to respect provider limits
- 🔄 **Easy Management** - Add, remove, and fetch plant data through the UI
- 📱 **Modern Config Flow** - Full UI configuration with helpful explanations at every step

## What Makes Plant Helper Different

Unlike basic plant monitoring integrations, Plant Helper:

1. **Works without physical sensors** - The soil moisture model calculates moisture levels using watering events and evaporation rates, even if you don't have a soil moisture sensor
2. **Caches everything locally** - Once plant data is downloaded, it's stored locally. No repeated API calls for the same plant
3. **Smart API usage** - Checks local cache → Perenual → Trefle fallback → iNaturalist enrichment, only calling what's needed
4. **Combines multiple data sources** - Gets the best information from each provider and merges it intelligently

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click the three dots in the top right
3. Select "Custom repositories"
4. Add `https://github.com/swetoast/ha-plant-helper` as an Integration
5. Click "Install" on the Plant Helper card
6. Restart Home Assistant

### Manual Installation

1. Download the [latest release](https://github.com/swetoast/ha-plant-helper/releases)
2. Extract and copy the `custom_components/plant_helper/` folder to your Home Assistant's `custom_components/` directory
3. Restart Home Assistant
4. Go to Settings → Devices & Services → Add Integration
5. Search for "Plant Helper"

## Quick Start

### 1. Get API Keys

**Required:**
- **Perenual** - Get a free key at [perenual.com/docs/api](https://perenual.com/docs/api)
  - Free tier: 100 requests/day

**Optional:**
- **Trefle** - Get a token at [trefle.io](https://trefle.io/)
  - Free tier: 500 requests/day
  - Used as fallback when Perenual doesn't have a plant

### 2. Set Up the Integration

1. Add the integration from Settings → Devices & Services
2. Enter your Perenual API key (required)
3. Optionally add your Trefle API key
4. Enable features:
   - **Trefle fallback** - Search Trefle when Perenual comes up empty
   - **iNaturalist enrichment** - Add extra photos and details (no API key needed)
5. Click Submit

### 3. Add Your First Plant

1. Go to the Plant Helper integration options
2. Select "Add Configured Plant"
3. Search by common name (e.g., "Snake Plant", "Monstera", "Pothos")
4. Link your sensors (all optional):
   - Room temperature
   - Room humidity  
   - Room light (lux)
   - Soil moisture (or let Plant Helper calculate it)
5. Give your plant a name

### 4. Monitor Your Plants

Plant Helper creates these sensors for each plant:

- **Plant Status** - Overall health and detailed attributes
- **Calculated Soil Moisture** - Smart watering model
- **Light Score** - Daily light accumulation
- **Temperature Stress** - Time outside safe temperature range
- **Health Score** - Overall wellness (0-100)
- **Care Action** - Next recommended action (water, fertilize, etc.)

## How It Works

### Lookup Order

When you search for a plant:

```
1. Local Database (instant, no API calls)
   ↓ (if not found)
2. Perenual API (primary data source)
   ↓ (if not found and enabled)
3. Trefle API (fallback)
   ↓ (optional enrichment)
4. iNaturalist (adds photos and observations)
```

### Smart Soil Moisture

Plant Helper can calculate soil moisture even without a physical sensor:

- Tracks watering events
- Models evaporation based on:
  - Room temperature
  - Room humidity
  - Light levels
  - Plant-specific water needs
- Updates in real-time as conditions change

If you add a physical soil moisture sensor later, Plant Helper uses that instead.

## Data Providers

### Perenual (Primary)

Provides comprehensive plant care data:
- Watering schedule and frequency
- Sunlight requirements (full sun, partial shade, etc.)
- Soil preferences
- Growth rate and mature size
- Toxicity information
- Pest and disease susceptibility
- Care level and maintenance needs
- Temperature ranges

### Trefle (Optional Fallback)

Adds botanical and taxonomic details:
- Scientific classification
- Growth characteristics
- pH preferences
- Temperature and humidity ranges
- Bloom periods
- Distribution data
- Additional photos

### iNaturalist (Optional Enrichment)

Enriches existing plant data:
- Research-grade observations
- Community photos
- Regional distribution
- Seasonal information
- Observation counts

## Configuration Options

Access through: Settings → Devices & Services → Plant Helper → Configure

### Integration Settings

| Setting | Description | Default |
|---------|-------------|---------|
| Perenual API Key | Primary plant database | Required |
| Trefle API Token | Backup database | Optional |
| Enable Trefle Fallback | Search Trefle when Perenual fails | Disabled |
| iNaturalist Enrichment | Add extra photos/details | Disabled |
| Update Interval | Sensor refresh rate (seconds) | 300 |

### Plant Management

- **Add Configured Plant** - Create a plant with sensors
- **Remove Configured Plant** - Delete plant device and sensors
- **Fetch Species to Cache** - Download plant data without creating sensors
- **View Plants** - See your monitored plants and cached species
- **Reset Database** - Clear all plant data (keeps settings)

## API Limits

Plant Helper respects provider rate limits:

| Provider | Daily Limit | Delay Between Requests |
|----------|-------------|------------------------|
| Perenual | 100 | None |
| Trefle | 500 | 0.6 seconds |
| iNaturalist | 300 | 1.0 seconds |

**Tip:** Use the local cache! Once a plant is fetched, it's stored locally and reused automatically.

## Sensors

### Integration-Level Sensors

- **Database Summary** - Total cached species count
- **Configured Plants Summary** - Active plants being monitored
- **API Status** (binary) - Provider connectivity and issues

### Per-Plant Sensors

Each configured plant gets:

1. **Plant Status** (main sensor)
   - Current state (healthy, needs water, stressed, etc.)
   - All attributes and calculated values
   - Linked sensor readings
   - Care recommendations

2. **Calculated Soil Moisture**
   - Percentage (0-100%)
   - Based on watering model or physical sensor
   - Updates as conditions change

3. **Daily Light Score**
   - Accumulated useful light (lux-hours)
   - Tracks if plant is getting enough light
   - Resets daily

4. **Temperature Stress Load**
   - Time spent outside safe temperature range
   - Helps identify climate issues

5. **Health Score**
   - Overall wellness (0-100)
   - Weighted combination of all factors
   - Easy at-a-glance monitoring

6. **Care Action**
   - Next recommended action
   - Examples: "Water soon", "Fertilize", "Increase light", "Monitor closely"

## Services

Plant Helper provides services for automation:

- `plant_helper.add_cached_plant` - Download plant data
- `plant_helper.remove_cached_plant` - Delete cached data
- `plant_helper.fetch_plant_data` - Refresh plant information
- `plant_helper.add_configured_plant` - Create monitored plant
- `plant_helper.remove_configured_plant` - Remove monitored plant
- `plant_helper.mark_fertilized` - Log fertilization event
- `plant_helper.mark_inspected` - Log inspection
- `plant_helper.reset_database` - Clear all data

## Examples

### Dashboard Card

```yaml
type: entities
title: My Plants
entities:
  - entity: sensor.monstera_status
    secondary_info: last-changed
  - entity: sensor.monstera_health_score
  - entity: sensor.monstera_soil_moisture
  - entity: sensor.monstera_care_action
```

### Automation: Water Reminder

```yaml
automation:
  - alias: "Remind me to water plants"
    trigger:
      - platform: state
        entity_id: sensor.monstera_care_action
        to: "Water soon"
    action:
      - service: notify.mobile_app
        data:
          title: "Plant Care"
          message: "Your Monstera needs watering!"
```

### Automation: Low Light Alert

```yaml
automation:
  - alias: "Low light warning"
    trigger:
      - platform: numeric_state
        entity_id: sensor.monstera_light_score
        below: 2000
        for:
          hours: 24
    action:
      - service: notify.mobile_app
        data:
          message: "Monstera isn't getting enough light"
```

## Troubleshooting

### Plant not found?

- Try different common names ("Pothos" vs "Devil's Ivy")
- Enable Trefle fallback in settings
- Check the API Status binary sensor for provider issues

### API rate limit exceeded?

- Use "Fetch Species to Cache" to pre-download plant data
- Avoid force-fetch unless necessary
- Check your API usage on provider dashboards

### Sensors not updating?

- Verify linked sensors are working
- Check update interval (Settings → Configure)
- Linked sensors trigger immediate updates regardless of interval

### Reset and start fresh

- Go to integration options → "Reset Plant Database"
- This keeps your API keys and settings
- Removes all cached and configured plants

## Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) for details.

### Development Setup

1. Fork the repository
2. Clone your fork
3. Create a feature branch: `git checkout -b feature/my-feature`
4. Make your changes
5. Test thoroughly
6. Commit: `git commit -m "Add my feature"`
7. Push: `git push origin feature/my-feature`
8. Open a Pull Request

## Support

- 🐛 [Report a bug](https://github.com/swetoast/ha-plant-helper/issues/new?template=bug_report.md)
- 💡 [Request a feature](https://github.com/swetoast/ha-plant-helper/issues/new?template=feature_request.md)
- 💬 [Discussions](https://github.com/swetoast/ha-plant-helper/discussions)

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for version history.

## Credits

### Data Providers

- [Perenual](https://perenual.com/) - Primary plant care database
- [Trefle](https://trefle.io/) - Botanical and taxonomic data
- [iNaturalist](https://www.inaturalist.org/) - Community observations and photos

### Inspiration

Built for plant lovers who want smart monitoring without buying dedicated sensors for every plant.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Disclaimer

Plant care data should be treated as guidance. Actual care needs vary based on plant age, pot size, soil type, room conditions, season, and local environment. Always observe your plants and adjust care accordingly.

---

Made with 🌱 for the Home Assistant community
