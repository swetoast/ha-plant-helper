# Entity reference

Plant Helper creates one device per plant. Unique IDs are based on the config entry, persistent plant UUID, and entity key. Renaming a plant does not intentionally replace its unique IDs.

## Sensors

### Status

A concise categorical care state such as a normal state or a direct care recommendation. Outdoor plants can report `watering_paused` when the soil is below the care profile but rain is expected soon; critically dry soil still recommends watering. Attributes are a user-facing summary and reason, and, when a forecast is available, weather context: placement, and for outdoor plants rain suppression, drying context, frost hours, and exposure, or external daylight for indoor plants.

### Moisture

Current plant moisture in percent. Device class: moisture. State class: measurement.

### Light

Current illuminance in lux. Device class: illuminance. State class: measurement.

### Temperature

Current temperature in degrees Celsius. Device class: temperature. State class: measurement.

### Health

A meaningful categorical plant-health state. The optional attribute is a short user-facing summary.

### Calibration

The current learning or calibration state. The optional attribute is calibration progress.

### Species

The resolved species context. The state is the resolved scientific name. Optional attributes are scientific name, common name, family, genus, watering category, and sunlight requirements, populated as the iNaturalist, Trefle, and Perenual providers return them. A local authenticated image URL is reserved for a future release. Provider names, raw responses, credentials, cache internals, and debug details are not exposed.

## Binary sensor

### Needs attention

Uses the Home Assistant problem device class. The sensor turns on only when the plant state indicates actionable attention is required. The optional attribute is a concise reason.

## Availability

- A plant being removed makes all of that plant's entities unavailable.
- An entity without its required state is unavailable.
- Missing optional provider data affects only the relevant entity.
- Provider failures do not make the complete plant device unavailable.

## Dynamic lifecycle

Adding a plant creates its entities. Editing updates the existing entities. Removing a plant removes its entities and associated runtime references rather than leaving inactive duplicates.
