# Entity reference

Plant Helper creates one device per plant. Unique IDs are based on the config entry, persistent plant UUID, and entity key. Renaming a plant does not intentionally replace its unique IDs.

## Sensors

### Status

A concise categorical care state such as a normal state or a direct care recommendation. Attributes are limited to a user-facing summary and reason when available.

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

The resolved species context. Optional attributes are scientific name, family, and the authenticated local image URL. Provider names, raw responses, credentials, cache internals, and debug details are not exposed.

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
