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
