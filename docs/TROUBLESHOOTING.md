# Troubleshooting

## Plant Helper is not in the integration list

- Confirm `<config>/custom_components/plant_helper/manifest.json` exists.
- Restart Home Assistant after copying or replacing files.
- Check the logs for import or syntax errors.

## A measurement entity is unavailable

An entity stays unavailable until it has a usable state. Confirm the selected
source entity exists and reports a numeric value. An unavailable optional
sensor does not affect the others.

## Calibration says "learning"

Expected. A plant judges against a generic profile until it has learned its own
range, which takes about two weeks of readings. It flips to `calibrated` on its
own. Moving a plant or changing its species restarts learning.

## Status says `insufficient_light`

Light is judged per day as cumulative exposure during daylight. Three low days in
a row raise it, and two bright days outside while the spot stayed dim point to
shading. Overcast days are forgiven for up to three days. Move the plant, add a
grow light (15 minutes or longer counts), or check the light sensor faces the
plant's leaves rather than a shadow.

## Status says `sensor_problem`

The moisture sensor has reported no valid reading for six hours, or every value
it reports has stayed exactly the same for five days (a frozen device). Check the
sensor's battery and connection in its own integration.

## A plant is marked `dormant`

A month of low light and a slightly cooler recent week mean the plant is resting.
Wet soil is tolerated longer and the watering prompt comes at a lower moisture
level. It lifts on its own as light returns.

## Species data is missing

- Enrichment is optional.
- Use a species name specific enough to match.
- Check Perenual or Trefle credentials and the Perenual access level.
- Provider outages, rate limits, and auth suspensions do not stop local
  monitoring.

## A species photo is missing

Photos must be HTTPS and resolve to a public address; redirects are re-checked.
Wrong content types, oversized downloads, huge dimensions, and undecodable
images are rejected. A failed refresh keeps the last cached photo if there is
one, otherwise the plant shows none.

## A plant will not remove

Retry from Configure > Remove plant and complete the confirmation. Removal uses
revision checks to avoid deleting a plant that changed mid-flow; if it was edited
elsewhere, reopen the removal flow.

## Entities remain after removal

Reload or restart Home Assistant, then check the entity and device registries.
Normal removal deletes the entities, registry entries, device, and stored state.

## Reporting a problem

Include the Home Assistant version, Plant Helper version, relevant log lines, the
affected entity, and steps to reproduce. Strip credentials and location before
sharing logs.
