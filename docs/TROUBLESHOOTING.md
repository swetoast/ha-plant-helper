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

Species data comes from the record you chose for each provider when the plant
was added. To change or fill it in, open the integration's options and choose
**Re-match species data**: pick the plant, optionally enter a different name to
search for, then choose (or skip) a record from iNaturalist, Trefle, and
Perenual in turn. Each entry says what it would contribute.

- A provider only appears when its API key is configured; iNaturalist needs none.
- Trefle often has taxonomy but no growth data for common houseplants; the
  Trefle step says so for each record, so you can skip it.
- Perenual supplies watering, sunlight, care level, pet and human toxicity,
  and whether a plant suits indoors. The free plan opens only records with ID
  3000 or lower, so on free the Perenual step offers only those; when a plant
  exists only as a paid record the step says so and offers Skip. Many
  houseplants sit above that range (the snake plant is record 7171, filed under
  its older name Sansevieria trifasciata), so on free they get no Perenual data.
- If the plan is set to paid but Perenual returns locked records, the step
  warns that the key looks like a free one.
- Plants added before per-provider matching still use the older name-based
  lookup until they are re-matched once.
- Fetched records are cached for six months, so restarts do not spend provider
  quota. Outages, rate limits, and rejected keys never stop local monitoring.

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
