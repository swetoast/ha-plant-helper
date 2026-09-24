# Plant Helper - Feature Roadmap (F1-F4)

> Status: F1-F4 all shipped (0.0.27-0.0.30).

> Purpose: pre-decide every design question so these four features can be built
> without stopping to ask. Order is fixed by dependency and risk: F1 (photos),
> F2 (light + humidity tracking), F3 (learned baselines), F4 (seasonal dormancy).
> F4 depends on F3. Each feature ships as its own release, pure logic tested,
> Home Assistant glue compile- and lint-checked (HA is not importable in the
> build sandbox, the same constraint the temporal work shipped under).

Cross-cutting rules (unchanged from the temporal work):
- Pure domain logic in `domain/`, thin HA glue in the top level.
- Raw measurement entities never change. New context rides on existing entities
  as attributes; no new primary entities unless a feature explicitly adds one.
- Every "default" numeric is a starting value to tune against fixtures.
- No dead code: a feature is wired end to end in the release that introduces it.

---

## F1 - Species photos (wire the image proxy)

Goal: show a real photo on `sensor.<plant>_species`. Providers already return an
image URL; the security-hardened `SpeciesImageProxy` already exists and is
tested. Nothing fetches or serves through it, and `schedule_enrichment` never
copies `image_url` into the entity attributes.

Decisions:
- Serve proxied local images only, never the raw provider URL. The proxy exists
  precisely to avoid the frontend fetching arbitrary external URLs (SSRF, privacy,
  no caching). `image_url` is set to the local path `/api/plant_helper/image/<digest>`.
- On proxy failure, omit `image_url` rather than fall back to the raw URL.
- Cache directory: `hass.config.path("plant_helper/images")`.
- Downloader does not follow redirects (the proxy validates each hop for SSRF)
  and caps the read at the proxy's MAX_DOWNLOAD.
- Garbage collection runs on a daily timer, never at startup (startup runs before
  enrichment repopulates the reference set, which would delete live images).
- Refresh happens inside `schedule_enrichment`, which is already async and already
  does provider I/O, so no new task type is needed.

Modules: new top-level `image_client.py` (aiohttp downloader returning the
proxy's `DownloadResponse`); `PlantHelperImageView` becomes a real
`HomeAssistantView`; runtime gains `async_configure_images`, an `image_proxy`
field, a daily GC timer, and the enrichment hook.

Tests: downloader response mapping with a fake session; `image_url` becomes the
local path when a candidate has an image and the proxy succeeds. Proxy internals
already covered.

Entities: `sensor.<plant>_species` gains a populated `image_url` (already an
allowed attribute).

---

## F2 - Light and humidity temporal tracking

Goal: give light and humidity the same trend-aware treatment moisture has,
feeding `health` and adding context, for both indoor and outdoor plants.

Decisions:
- No new primary entities. Light and humidity adequacy ride on `sensor.<plant>_health`
  and add `light_context` / `humidity_context` attributes to `sensor.<plant>_status`.
  Moisture remains the sole driver of `care_status`; light and humidity can raise
  `health` to `watch` but never set `needs_attention` on their own.
- Reuse `ObservationHistory`: `PlantObservation` already carries soil temperature;
  extend it with light and humidity so one history per plant holds every signal.
- Light is judged on the daily integral (a plant cares about total daily light,
  not the instantaneous lux), using the already-scaffolded `DailySummary`.
  Humidity is judged on a rolling average against the profile.
- Adequacy buckets share one vocabulary: `low` / `adequate` / `high`.
- Precedence is the existing `status.py` ordering; moisture outranks the rest.

Modules: pure `domain/temporal/light.py` and `domain/temporal/humidity.py`;
`observation.py` gains fields; `history.py` gains daily-summary and rolling-mean
helpers; runtime records the extra signals and merges the health verdict.

Tests: daily light integral bucketing; humidity rolling adequacy; health rises to
`watch` on sustained inadequacy; moisture attention is never overridden.

Entities: `health` reflects light/humidity; `status` gains `light_context` and
`humidity_context` attributes (both placements, `None`-dropped when unavailable).

---

## F3 - Learned per-plant baselines (wire learning.py)

Goal: replace the static profile bands with what is actually normal for each
plant, so judgement improves the longer it runs. `learning.py` is already built.

Decisions:
- Calibration gate: a baseline is "learned" after 14 days of coverage at high
  confidence with at least one full wet-to-dry cycle observed. Until then,
  `calibration` reads `learning` and the static profile bands are used.
- Once calibrated, the learned low/high replace `PROFILE_BANDS` inside
  `evaluate_moisture`; the profile becomes the fallback and the seed, not the law.
- The learned band is the plant's observed comfortable range (robust percentiles
  of the dry-cycle troughs and post-water peaks), clamped to sane bounds so a
  stuck sensor cannot learn a nonsense band.
- Placement change resets calibration: `decide_placement_transition` already
  computes `clear_active_samples` / `reset_placement_timers`; wire it so a plant
  moved indoor/outdoor relearns.
- Persistence: bump the temporal store to schema v2 with a `learning` section per
  plant; v1 payloads restore with no baseline (calibration restarts), never crash.
- Species change clears the learned baseline (different plant, different normal).

Modules: wire `LearningRuntime`/`LearningState` into runtime and `evaluate_moisture`
(band source becomes learned-or-profile); extend `store.py` to v2; add a
migration path.

Tests: calibration completes only after the gate; learned band overrides profile;
placement/species change resets; v1 store restores cleanly; nonsense readings are
clamped out.

Entities: `calibration` moves `learning` to `calibrated`; `status` `reason`
distinguishes learned vs profile judgement.

---

## F4 - Seasonal dormancy (depends on F3)

Goal: expect less water in dormancy (winter) and more in active growth, so a
correctly resting plant is not nagged.

Decisions:
- Dormancy is read from the interpretation signals already computed: outdoor
  `growth_season`, indoor `season` / `day_length`. No new sensors.
- Dormancy applies a seasonal multiplier to the drying coefficient (dormant =
  slower expected drying = longer wet allowance) and widens patience before
  `needs_water`. It reuses the F4-era `drying.py` machinery rather than adding a
  parallel path.
- The seasonal multiplier is bounded like the drying coefficient so a season can
  never fully silence a genuinely dry or genuinely waterlogged plant.
- Learned baselines (F3) shift with season only if enough seasonal history exists;
  otherwise the multiplier alone applies. This is why F4 follows F3.

Modules: pure `domain/temporal/season.py` (signals -> multiplier); `drying.py`
composes it into the coefficient; runtime passes the season signals through the
environment mapping it already assembles.

Tests: dormant multiplier extends the wet allowance and needs-water patience;
active season is neutral; bounds hold; a critically dry plant still escalates in
dormancy.

Entities: `status` `drying_context` and `reason` reflect dormancy; no new entities.
