# Troubleshooting

## Plant Helper does not appear when adding an integration

- Confirm the path is `<config>/custom_components/plant_helper/manifest.json`.
- Restart Home Assistant after copying or replacing the integration.
- Check Home Assistant logs for import or syntax errors.

## A measurement entity is unavailable

An entity remains unavailable until its own usable state exists. Check that the selected physical entity exists, has a numeric state where required, and uses the expected measurement type. An unavailable optional measurement should not make unrelated entities unavailable.

## Species data is missing

- Species enrichment is optional.
- Confirm the species name is specific enough for exact or strong matching.
- Verify configured Perenual or Trefle credentials and the selected Perenual access level.
- Temporary provider failures, rate limits, or authentication suspension do not stop local plant monitoring.

## A species image is missing

Images must use HTTPS and resolve only to public network addresses. Redirects are checked again. Unsupported content types, oversized downloads, excessive dimensions, decompression limits, or failed image decoding are rejected. When refresh fails, the last valid cached image is retained when available.

## A plant cannot be removed

Retry from **Configure > Remove plant** and complete the confirmation step. Removal uses revision checks to avoid deleting a plant that changed during the flow. If the plant was edited in another flow, reopen the removal flow to use the current revision.

## Configuration changed in another flow

Close the older flow and reopen it. Storage revisions prevent stale add, edit, and removal submissions from overwriting newer changes.

## Entities remain after removal

Reload or restart Home Assistant, then check the entity and device registries. The normal removal path deletes loaded entities, registry entries, the plant device, runtime ownership, and stored plant state.

## Reporting a problem

Include the Home Assistant version, Plant Helper version, relevant Home Assistant log lines, the affected entity type, and the steps that reproduce the problem. Remove credentials and personal location information before sharing logs.
