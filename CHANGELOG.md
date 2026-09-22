# Changelog

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
