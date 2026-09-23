# Plant Helper 0.0.9 lifecycle audit

## Scope

The audit traced initial configuration, entry setup, platform forwarding, stored-plant restoration, add, edit, remove, reconfigure, entity publication, registry cleanup, pending cleanup recovery, and unload behavior.

## Findings and corrections

### Add lifecycle

A plant was persisted before runtime activation. Any later listener, entity-registration, or evaluation error escaped to the options form, which then claimed that no plant had been added. The durable commit is now authoritative. Post-commit activation failure schedules reconciliation and returns the committed result instead of reporting a false save failure.

### Edit lifecycle

Edit had the same post-commit error boundary. A successfully persisted revision could be reported as a failed edit if listener replacement or evaluation failed. Post-commit failures now schedule reconciliation without misrepresenting the saved revision.

### Remove lifecycle

Removal deleted the plant from storage before entity and registry cleanup. A later cleanup exception returned an error even though the plant no longer existed. Cleanup progress was stored, but setup never resumed pending cleanup. Removal is now divided into a durable deletion and idempotent cleanup steps. The form succeeds after durable deletion. Incomplete cleanup stays recorded and is retried after platforms load during the next integration setup.

### Entity lifecycle

Newly queued entities could receive a state write before Home Assistant attached them. Removal could also encounter queued entities that had no Home Assistant instance yet. State writes and removal now check attachment state.

### Registry ownership

Entity cleanup previously used a broad UUID substring match. Cleanup now requires the Plant Helper platform, the active config entry, and the exact Plant Helper unique-ID prefix for the selected plant.

### Form behavior

Removal previously executed whenever the confirmation form was submitted, including a false checkbox value. A checked confirmation is now required. Empty remove menus abort cleanly. The soil-moisture selector remains constrained to moisture sensors. Battery supports both numeric battery sensors and categorical soil-sensor battery-state entities.

### Setup and recovery

Runtime initialization still precedes entity platform forwarding. Pending removal cleanup now runs after both entity platforms are loaded, allowing live entities, entity-registry records, and device-registry records to be reconciled in the correct order.

## Public contract

No entity names, entity keys, unique-ID format, units, device classes, state classes, plant UUIDs, configuration fields, or storage schema versions were changed.

## Verification coverage

Regression coverage includes durable add and edit commits, post-commit activation failures, entity attachment races, durable removal, partial cleanup, startup retry, confirmation enforcement, exact cleanup ownership, fixture-backed physical sensor data, Open-Meteo forecast data, Perenual responses, and Trefle responses.

## 0.0.11 compatibility follow-up

Home Assistant treats an entity's `entity_description` attribute as a framework `SensorEntityDescription` or `BinarySensorEntityDescription`. Plant Helper incorrectly assigned its smaller domain-only `EntityContract` to that reserved attribute. Home Assistant then accessed framework fields that the internal contract intentionally did not provide. Version 0.0.11 stores the internal contract separately and continues assigning supported entity properties directly.

Plant device removal also now checks every entity-registry reference before deleting a device. A device remains while any Plant Helper or foreign entity, including a template entity, references it. This prevents dangling device IDs.

## 0.0.12 entity completeness follow-up

The physical runtime already collected humidity and battery values, but the public entity contract omitted both values. Version 0.0.12 adds `sensor.<plant>_humidity` and `sensor.<plant>_battery` without changing existing entities. Humidity is a percentage measurement. Battery remains a generic sensor because the verified source contract can be either numeric 0 through 100 or categorical `high`, `middle`, or `low`; no categorical value is converted into a guessed percentage.

The calibration entity previously displayed `not_configured` and `progress: 0`, which incorrectly suggested unfinished user setup. Plant Helper currently relies on the selected source sensor's reading rather than requiring a separate Plant Helper calibration operation. The existing calibration entity is therefore retained but now reports `source_sensor` with a direct explanatory summary.

## 0.0.18 options-preservation and image-exposure follow-up

The plant-management options flow returned an empty options set on every add, edit, and remove. Because a Home Assistant options flow replaces the stored options with its returned data, each plant change wiped the global settings (latitude, longitude, Perenual and Trefle credentials, access level, update interval). A registered entry update listener then reloaded the whole config entry on that write, contradicting the dynamic no-reload plant lifecycle. The flow now returns the current options unchanged, so global settings survive and an unchanged options write no longer forces a reload. Global reconfiguration continues to reload exactly once through the config flow's update-and-reload path.

The species entity previously published the raw provider image URL as an attribute, bypassing the intended local validated-image path. The runtime no longer copies the third-party URL into entity attributes. The local authenticated image path remains reserved in the entity contract for a later release that wires the image proxy.

No entity IDs, unique-ID format, units, device classes, state classes, plant UUIDs, configuration fields, or storage schema versions were changed.
