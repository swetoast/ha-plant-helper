# Changelog

## 0.0.7 - 2026-09-22

- Added sanitized Open-Meteo, Perenual, and Trefle regression fixtures from real provider responses.
- Added real forecast coverage for rain accumulation, wet hours, ET0, radiation, timezone metadata, surface soil temperature, and modelled surface soil moisture.
- Kept modelled Open-Meteo soil moisture separate from the physical plant moisture percentage entity.
- Updated Perenual handling to accept both search lists and single details objects.
- Distinguished Perenual paid-plan restrictions from ordinary not-found responses.
- Updated Trefle handling to accept a single species details object.
- Added tests for inconsistent Trefle summary metadata, categorized images, nullable botanical fields, and sanitized provider data.

## 0.0.6 - 2026-09-22

- Added sanitized regression fixtures from two real Home Assistant soil-sensor devices.
- Added coverage for numeric moisture, temperature, humidity, illuminance, and battery readings.
- Added coverage ensuring categorical battery states are not misreported as numeric percentages.
- Preserved calibration, sampling, warning, link-quality, dry-state, and temperature-unit evidence without treating those control entities as plant measurements.

## 0.0.5 - 2026-09-22

- Connected configured physical source entities to the Plant Helper runtime.
- Seeded current moisture, temperature, light, humidity, and battery values during startup.
- Added live state-change subscriptions and debounced reevaluation.
- Added functional status, health, calibration, species, and attention states without changing entity IDs or the entity contract.
- Added real listener, task, entity-registry, device-registry, and unload cleanup.
- Preserved optional provider isolation so enrichment failures cannot break core plant monitoring.

## 0.0.4 - 2026-09-22

- Fixed plants being created without sensor or binary-sensor entities.
- Entity platforms now reconcile persisted plants directly during setup.
- Add Plant now explicitly asks every loaded platform to create the new plant entities after persistence.
- Entity creation is idempotent, so runtime notifications and explicit reconciliation cannot create duplicates.

## 0.0.3 - 2026-09-22

- Fixed Add plant failing because the runtime storage backend was never created or loaded.
- Runtime storage now loads before sensor and binary-sensor platforms are forwarded.
- Existing stored plants are restored into the runtime collection during setup.
- Added safe operational defaults for optional runtime hooks used by plant management.
- Added server-side exception logging for unexpected Add plant failures.

## 0.0.2 - 2026-09-22

- Fixed HACS installation packaging so all runtime domain modules are installed inside `custom_components/plant_helper`.
- Fixed the Home Assistant config-flow import failure reported as `Invalid handler specified`.
- Added isolated-package tests that import the integration and config flow without repository-root helper packages.

## 0.0.1 - 2026-09-22

Initial GitHub and HACS repository release.

- Added shared configuration and reconfigure flows.
- Added revision-safe persistent storage.
- Added dynamic add, edit, and remove plant flows.
- Added event-driven physical sensor processing.
- Added learning and placement runtime behavior.
- Added forecast and air-quality collectors with stale-data preservation.
- Added indoor and outdoor interpretation.
- Added optional Perenual, Trefle, and iNaturalist species enrichment.
- Added HTTPS-only authenticated species-image proxy with SSRF protection, image limits, thumbnails, content-addressed caching, ETags, garbage collection, and stale-image preservation.
- Added the final compact entity contract with seven sensors and one problem binary sensor per plant.
- Added cumulative integration, privacy, translation, manifest, compile, and packaging verification.
- Added HACS metadata, GitHub validation workflows, brand assets, public documentation cleanup, and the post-release maintenance plan.
