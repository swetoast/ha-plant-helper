# Temporal Soil Engine - Implementation Plan

## Relationship to the other documents

`temporal_sensor_roadmap.md` is the specification. `execution_roadmap.md`
sequences the whole component. This document is the concrete build plan for the
first and largest slice: replacing the static soil interpretation with a
temporal engine. It resolves the open decisions into specific choices and
breaks the work into small, independently shippable steps so the development
cycle stays clean. Every choice marked "default" is a starting value to tune
against fixtures, not a fixed constant; veto any of them before we start.

## Scope

Changes: the interpretation entities driven by the soil sensor, all of which
already exist and keep their IDs.

- `sensor.<plant>_status` (`care_status`)
- `sensor.<plant>_health` (`health`)
- `binary_sensor.<plant>_needs_attention` (`needs_attention`)

Does not change: the raw measurement passthroughs. These are the current
reading and stay exactly as they are.

- `sensor.<plant>_moisture`, `_temperature`, `_humidity`, `_light`, `_battery`

This slice covers moisture only (soil moisture, with soil temperature as
context). Air humidity and light follow the same pattern in later slices and
are out of scope here.

## Decisions resolved

1. **Pure engine, injected clock.** The engine is a pure domain module taking
   `(history, prior_state, now, profile, environment)` and returning a decision
   plus the next persisted state. Home Assistant supplies the clock and events.
   This lets the roadmap's timeline scenarios run as ordinary `tests/domain`
   tests in any environment, not only the Home Assistant harness.
2. **Separate versioned store, coalesced writes.** Temporal data lives in its
   own Home Assistant `Store` (`plant_helper_temporal`), never in the config
   entry. Writes are debounced and flushed on a timer and on shutdown, never one
   write per sensor event. No migration of the existing config store is needed;
   the temporal store starts empty and rebuilds from live readings.
3. **One canonical status vocabulary.** A single `domain/temporal/status.py`
   defines the status and health states and their precedence. `watering_paused`
   from 0.0.20 is kept as an outdoor status. The one breaking string change is
   `water_soon` becoming `needs_water`; it gets a CHANGELOG note, and it is worth
   grepping your own automations and dashboards for `water_soon` before release.
4. **Confidence is defined numerically.** Confidence is a function of coverage
   and gaps over the last 24 hours: high at >= 18 h coverage and gap ratio
   < 0.25, medium at >= 8 h, otherwise low. Escalating to `too_wet` or `too_dry`
   requires confidence of at least medium. These are defaults.
5. **Cleanup scoped to this track.** `domain/storage_revision.py` is superseded
   by the new store and is removed as part of step P2. The flow models,
   `learning`, and the image proxy are orthogonal to soil work and stay untouched
   here; they are handled on their own tracks in `execution_roadmap.md`.

## Module layout

New package `custom_components/plant_helper/domain/temporal/`:

- `status.py` - status and health enums, precedence order, single source of truth.
- `observation.py` - `PlantObservation`, `DailySummary` dataclasses.
- `history.py` - `ObservationHistory`: append with deduplication, bounded rolling
  window, daily rollup. Pure, no I/O.
- `moisture.py` - `evaluate_moisture(...)`: watering detection, state machine,
  duration gating, `k_drying`. Pure.
- `store.py` - serialize and restore the temporal store; validate restored
  timestamps. Pure transform; the Home Assistant `Store` object is owned by the
  runtime.

Runtime hooks (thin glue only, no logic): `runtime.evaluate` records an
observation and calls `evaluate_moisture`; a new background tick advances
durations; `async_configure_temporal` opens the store; `async_unload` flushes it.

## Data model

```python
@dataclass(frozen=True, slots=True)
class PlantObservation:
    observed_at: datetime
    moisture: float | None
    soil_temperature: float | None
    moisture_valid: bool
    soil_temperature_valid: bool

@dataclass(frozen=True, slots=True)
class TemporalMoistureState:
    status: str
    state_since: datetime | None
    last_watering_event: datetime | None
    cycle_peak_moisture: float | None
    drying_rate_per_hour: float | None
    adjusted_wet_duration_limit: float | None
    confidence: str
```

`DailySummary` (one per local day, for multi-day interpretation) is added in the
light/temperature slices; moisture needs only the rolling window plus the small
state above.

## Engine contract

```python
def evaluate_moisture(
    history: ObservationHistory,
    prior: TemporalMoistureState | None,
    now: datetime,
    profile: str,
    environment: Mapping | None = None,
) -> tuple[MoistureDecision, TemporalMoistureState]:
    ...
```

`MoistureDecision` carries `status`, `health`, `needs_attention`, `summary`,
`reason`, `since`. The runtime writes these onto the existing entity state keys.
The function is pure: same inputs, same outputs, no clock or I/O of its own.

## Tick and observation flow

- **Sensor push (existing 350 ms debounce):** record a `PlantObservation`
  (subject to deduplication), then run `evaluate_moisture`.
- **Background evaluation tick (new, default 60 s):** run `evaluate_moisture`
  with the current `now` so durations advance even when moisture is unchanged.
  This tick records no observation and triggers no provider or weather request.
- Decouple this from the weather timer added in 0.0.20. Weather keeps its own
  fetch cadence; the evaluation tick is separate and cheap.

Deduplication defaults: skip a new sample when `abs(delta_moisture) < 0.5` and
less than 10 minutes have passed and validity is unchanged. Always record
validity transitions and sharp moisture rises.

## Storage schema and write policy

```json
{
  "version": 1,
  "plants": {
    "<uuid>": {
      "rolling": [ /* bounded observations, ~48 h, cap ~500 */ ],
      "moisture_state": { /* TemporalMoistureState */ }
    }
  }
}
```

Write policy: coalesce and debounce; flush on a timer and on unload. Restart
behavior follows roadmap section 4: restore rolling state and moisture_state,
resume duration timing only when restored timestamps are valid, and never
escalate health from a single restored or single fresh sample.

## Build sequence

Small steps, each shippable and tested on its own.

### P0 - Foundation

- `status.py`, `observation.py`, `history.py` (dedup, bounded window,
  same-name isolation). No entity behavior change yet.
- Tests: deduplication, retention bound, valid-zero preserved, invalid readings
  excluded, two plants with the same name keep separate histories.

### P1 - Moisture state machine (fixes the live bug)

- `moisture.py`: watering-event detection and the wet/dry state machine with a
  static wet-duration limit. Wire `runtime.evaluate` to record an observation and
  set status/health/needs_attention from the decision.
- Defaults: watering rise >= 5 points within <= 90 min with valid before and
  after; reversals within +/- 2 points ignored; static wet-duration limit 72 h.
- This is where a single `47%` becomes `wet` with health good and attention off,
  instead of `too_wet`.
- Tests: roadmap scenarios 1 to 7 and 24; single elevated reading never
  `too_wet`; probable watering yields `recently_watered`; noise creates no event.

### P2 - Persistence and restart

- `store.py` plus the Home Assistant `Store` wiring; coalesced writes; restore
  with timestamp validation. Remove `storage_revision.py`.
- Tests: scenarios 17 and 18 (sensor unavailable mid-cycle, restart mid-cycle);
  restart does not reset active duration; writes are batched, not per event.

### P3 - Background tick and duration escalation

- New evaluation tick, decoupled from weather. `staying_wet` and `too_wet`
  become reachable only after sustained duration with confidence >= medium.
- Tests: scenarios 4 and 5; wetness escalates only after the duration passes;
  attention stays off through `recently_watered`, `wet`, and `drying`.

### P4 - Environmental drying coefficient

- `k_drying` and the dynamic wet-duration limit (bounded: no more than 35 %
  shorter, no more than 100 % longer). Realized moisture slope overrides
  predicted drying (the roadmap's critical safety rule).
- Tests: low expected drying extends the allowance; strong expected drying
  shortens it; a real drying slope beats the prediction.

### P5 - Status precedence and summaries

- Deterministic status precedence and the compact `summary` / `reason` / `since`
  attributes.
- Tests: precedence is deterministic; summaries are plain language; attributes
  stay limited to the three allowed fields.

## Testing note

The point-in-time soil fixtures validate parsing and normalization only. The
timeline scenarios use synthetic observation sequences with an injected `now`,
which is exactly what the pure engine enables. Each step also keeps the existing
regression guarantees: measurement entities still update immediately, entity IDs
are stable, plant CRUD still works, and no raw temporal state leaks into
attributes.

## Not in this plan

Air humidity and light temporal tracking, learned baselines, seasonal dormancy,
VPD as a full replacement, and partial-watering detection. Those follow in later
slices per `execution_roadmap.md`.
