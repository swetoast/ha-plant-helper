# Plant Helper Execution Roadmap

> Status: historical sequencing plan. The work it sequences has shipped; the
> user documentation and `CHANGELOG.md` describe current behavior.

## Purpose

One ordered plan from the current release toward the full design in
`plant_helper_design_document.md` and `temporal_sensor_roadmap.md`. Read this
before starting any feature so releases build on each other instead of landing
scattered. This document sequences the work and records the decisions that
gate it; the two design documents remain the detailed specification.

## Development baseline

Plant Helper `0.0.21`. Note the temporal roadmap still names `0.0.17` as its
baseline; the fixes and wiring since then (options preservation, species
exposure, Open-Meteo) change some of its assumptions, tracked under Open
decisions below.

## Current state

Implemented and wired:

- Config and reconfigure flows, plant add/edit/remove with optimistic locking, storage.
- Physical sensor processing: 350 ms debounce, numeric and categorical battery.
- Entity contract: nine sensors plus one binary sensor, dynamic entity lifecycle.
- Species enrichment chain (iNaturalist, Trefle, Perenual) surfaced on `species_context`.
- Open-Meteo forecast and air quality: fetch, mapping, cache, periodic coordinator; care evaluation consumes the cached environment.
- Care decision: static moisture band plus outdoor rain suppression (`watering_paused`).

Wired but shallow:

- Open-Meteo supplies rain, drying, frost, exposure, and daylight radiance context, but does not yet surface sunrise, sunset, or daylight duration (the indoor request omits daily fields and the collector does not parse daily). The periodic tick is coupled to weather refresh rather than to plant-state advancement.

Dead or unwired (parallel implementations that do not drive the component):

- `domain/setup_flow.py`, `domain/options_flow.py`, `domain/reconfigure_flow.py` (the flows in `config_flow.py` and `options.py` do not delegate to them).
- `domain/storage_revision.py` (storage uses inline revision handling).
- `domain/learning.py` (runtime holds a `learning` slot that is never populated).
- `domain/placement.py` transition handling (`handle_placement_change` is a no-op).
- The cached `SpeciesEnrichment` class in `domain/enrichment.py` (the chained variant is used and re-queries providers on every startup).
- The image proxy (`PlantHelperImageView`, `SpeciesImageProxy`) is unwired; `image_url` is reserved but never populated.

Known limitation driving the temporal work: care is a static band comparison, so a single `47%` reading is interpreted immediately with no time context. The confirmed live problem (one reading escalating to `too_wet`) is not fixed until the moisture-cycle engine lands.

## Open decisions (resolve before the temporal work)

1. **Status vocabulary is a breaking change.** The temporal roadmap renames `water_soon` to `needs_water` and adds roughly nine new states. Any user automation or dashboard keyed on current status strings breaks. Decide: clean break with a documented migration note, or keep back-compat aliases for a release. Also decide how `0.0.20`'s `watering_paused` folds into the new outdoor states, since the roadmap's status list omits it.
2. **Kill or wire the dead parallel modules.** For each of the flow models, `storage_revision`, the cached `SpeciesEnrichment`, `learning`, and the image proxy: either wire the live code to delegate to it, or delete it. Building temporal work on top of an ambiguous base is how the scatter started. The flow models and `storage_revision` are the most urgent because the temporal storage work touches the same area.
3. **Storage version and migration.** Temporal history, daily summaries, and learned baselines need their own storage, versioned, with a migration from the current single-record store. Decide separate `Store` keys versus sections in one record. Restart-safety and write batching are requirements, not options.
4. **Confidence thresholds.** The roadmap leans on `confidence: low/medium/high` and "uncertainty hold" without numbers. Pin these as a function of sample-coverage hours and gap ratio before Phase 2, or the escalation-suppression rules are untestable.
5. **Open-Meteo daylight extension.** Phase 4 needs sunrise, sunset, and daylight duration surfaced for indoor plants too. Confirm extending the forecast request and collector for this is in scope for T3.

## Cross-cutting rules (apply to every release)

- **Pure engine, injected clock.** The temporal engine is a pure domain module: `evaluate(observations, persisted_state, now) -> decision`. Home Assistant injects the clock and events. This is what lets the twenty-five timeline scenarios run as pure tests here, not only in the Home Assistant harness.
- **One canonical status enum.** Define the status and health vocabularies in a single module and reference it everywhere; reconcile the differing lists in roadmap sections 5, 9, and 13 into that one source.
- **Compatibility.** Preserve config entry, plant UUIDs, device identifiers, entity IDs, unique IDs, units, device classes, and state classes. No new public entities. Public attributes stay compact: `summary`, `reason`, `since`.
- **Storage discipline.** Batch and coalesce writes; one sensor event must not force a disk write. Bound the buffers (about 48 hours rolling, about 30 days of daily summaries). Validate restored timestamps before resuming duration timing.
- **Test policy.** Every phase ships pure timeline tests in `tests/domain` (runnable without Home Assistant) plus the behavioral tests from design section 44 in the Home Assistant harness (CI). No new source-string snapshot tests; the invariants the removed snapshots implied belong in the section 44 behavioral suite.

## Release sequence

Each release preserves its complete ZIP and restore file.

### T0 - Foundation and cleanup

- Resolve Open decision 2 (kill or wire each dead module).
- Storage v2 with migration (Open decision 3); canonical status enum (cross-cutting rule).
- Observation model, rolling and daily buffers, deduplication, batched writes, injected clock.
- Decouple plant-state advancement from weather refresh (two ticks, or one tick that never forces provider fetches).
- Definition of done: history persists and restores; identical values do not cause excess writes; existing entities unchanged; the pure timeline test harness exists.

### T1 - Moisture-cycle engine (roadmap Phase 2, roadmap Release 1)

- Watering-event detection, wet and dry progressions, `k_drying`, dynamic wet-duration limit.
- Reconcile `watering_paused` into the new outdoor states (Open decision 1).
- Fixes the live `47% -> too_wet` problem.
- Definition of done: roadmap timeline scenarios 1 to 7, 17, 18, 24 pass; a single elevated reading never yields `too_wet`.

### T2 - Temperature and humidity duration (roadmap Phase 3, roadmap Release 2)

- Duration tracking; combined cold-wet and warm-dry interpretation.
- Replace the abstract vapor term with a VPD (Tetens) calculation as the internal stress metric.
- Definition of done: scenarios 14 to 16; brief excursions do not move health.

### T3 - Light-exposure engine (roadmap Phase 4, roadmap Release 3)

- Open-Meteo daylight extension (Open decision 5) plus Astral fallback chain.
- Natural versus supplemental lux-hours, duration gating, source weighting, classifications.
- Definition of done: scenarios 8 to 13 and 19 to 22; forecast failure falls back without false light alerts.

### T4 - Combined summaries and learned baselines (roadmap Phases 5 and 6, roadmap Release 4)

- Status precedence, natural-language summaries; wire `learning.py` for per-pot learned baselines.
- Long-duration regression coverage.
- Definition of done: scenarios 23 and 25 plus full regression; health changes only on sustained evidence.

### E - Enrichment track (independent of the temporal critical path)

- Species cache (design section 34): stop re-querying providers on every startup.
- Image proxy (design section 38.1): populate `image_url` through the local cached proxy.
- Slot between temporal releases as convenient; not blocking.

## Deferred / out of scope

- Seasonal dormancy detection, VPD as a full replacement of the duration trackers, and partial-watering (volume-deficit) detection all depend on learned baselines and follow T4.
- Satellite Radiation API (design section 27).
- Any new public entity, and any raw temporal state exposed as attributes.
