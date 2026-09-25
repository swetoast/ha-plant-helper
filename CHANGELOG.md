# Changelog

## 0.0.46 - 2026-09-25

Perenual free and paid tiers, and only the useful part of each provider.

Established from live Perenual responses on a free key: search returns every
record, but records the key cannot open carry an "upgrade access" placeholder
image; species details work for IDs up to 3000 and return HTTP 429 "Please
Upgrade Plan" above that; and even an open free record replaces the
Supreme-only fields (watering volume, depth and period, sunlight hours,
temperature tolerance) with "Upgrade Plan To Supreme" text.

- The Perenual plan setting now decides what the Perenual step offers. Free:
  only records the key can open; when a plant exists only as a paid record the
  step says so and offers Skip (the snake plant, record 7171, is paid-only).
  Paid (Premium or Supreme): every record, with a warning when the results show
  the key is actually on the free plan.
- Perenual records keep only the care-relevant core: watering, watering interval,
  sunlight, care level, growth rate, indoor, drought tolerant, and toxicity to
  pets and humans (the last five new on the species sensor). Deliberately
  dropped: images (signed URLs expiring within a day), the hardiness-map and
  care-guide URLs (Perenual embeds the API key in them), and the Supreme-only
  fields, whose real format has not been seen.
- Real free-tier details (record 1469) and the real paywall response (record
  7171) are test fixtures, with the embedded API key redacted.

## 0.0.45 - 2026-09-25

Per-provider matching checked against live Perenual responses.

- Perenual has the snake plant only under its older name (record 7171,
  Sansevieria trifasciata; "Dracaena trifasciata" returns nothing). The Perenual
  step already searches the chosen name, its synonyms and the plant name, and
  now provably finds it on the second search and stops there to spare quota.
- Records a key cannot open are detected per record: Perenual replaces their
  image with an "upgrade access" placeholder. Such records are labelled as
  needing a paid plan and are never preselected. This works even when the
  access-level setting is wrong.
- Perenual images are no longer used anywhere. Every image URL Perenual returns
  is signed and expires within a day (and restricted records only carry the
  placeholder), so a cached URL would go stale; photos come from iNaturalist or
  Trefle.
- Exact matching compares scientific names only. Common names are shared
  across species (Perenual lists Sansevieria patens as "snake plant"), so a
  common-name hit could have preselected the wrong plant.
- Live Perenual search responses (free plan) added as fixtures; the flow test
  now runs on them.

## 0.0.44 - 2026-09-25

Species enrichment rebuilt around per-provider matching.

- Why it did not work. The species you picked while adding a plant was thrown
  away: enrichment re-searched iNaturalist by name at every start and then
  matched Trefle and Perenual by name as well, silently dropping any provider
  whose name matching missed. Perenual could never supply watering or sunlight
  at all, because those fields exist only on its species details endpoint and
  the integration only ever called the species-list search.
- Per-provider matching. Adding a plant now walks one step per configured
  provider (iNaturalist, then Trefle, then Perenual), each listing that
  provider's records with a Skip option and a line saying what the record would
  contribute: whether Trefle has growth data for it, and whether a Perenual
  record needs a paid plan for care data. Later steps search with the chosen
  record's name and synonyms, so iNaturalist's older name (Sansevieria
  trifasciata) still finds Trefle's accepted species (Dracaena trifasciata). The
  chosen record IDs are stored on the plant as `species_sources`.
- Enrichment by ID. Each chosen record is fetched directly (Trefle
  `/species/{id}`, Perenual `/species/details/{id}`) and merged; nothing is
  re-matched at runtime, and a skipped or failing provider cannot disturb the
  others. Fetched records are cached for six months so frequent restarts do not
  spend Perenual's small free quota; a failed fetch falls back to the cached
  record, and a record the Perenual plan does not cover is remembered for two
  weeks instead of retried each start. Perenual's "Upgrade Plans" placeholder
  values are treated as missing data, never shown.
- New options menu entry, Re-match species data, to redo or skip any provider
  for an existing plant. Plants added before this release keep the older
  name-based lookup until re-matched once. Ordinary edits keep the chosen
  records.
- Tests use the live Trefle search and detail responses and a stubbed Home
  Assistant flow that drives the real options flow end to end.
- Correction to 0.0.41: `sensor.<plant>_calculated_moisture` and
  `sensor.<plant>_drying_modifier` were never Plant Helper entities; they come
  from another integration and can be removed under Settings > Entities. The
  retired-entity pruning added then is correct but only ever touches Plant
  Helper's own entries.

## 0.0.43 - 2026-09-25

Calibrated against live data, and learned baselines now drive judgments.
Two weeks of real Home Assistant recorder history from two Zigbee soil sensors
were replayed through the engine; that replay is now a regression test
(`tests/domain/test_live_replay.py`). Before these fixes the snake plant, going
through two perfectly normal watering cycles, raised `too_wet` attention for
about 40 hours and sat in Health `watch` 45% of the time, and the second plant
was in `watch` 29% of the time for healthy 70-76% air humidity. After them the
snake plant raises no alerts and is `good` 97% of the time, and the second plant
raises exactly its two genuine dry spells.

- Drying detection. Soil counted as drying only at 0.5%/h (12 points a day)
  over 6 hours; real pots dry 1-10 points a day and report whole percentages, so
  a steadily drying pot read as stalled and escalated to `too_wet`. Drying is now
  a decline of 0.05%/h or more over up to 48 hours, measured from the last
  watering; two daily cycles average out the probe's ~8 point day/night swing.
- Watering detection. The fixed 5 points in 90 minutes caught the probe's
  day/night swing as waterings (for example 03:18 on Sep 18) and missed slow
  soaks that rose 18 points over several hours. The rise threshold now scales
  with each probe's own noise (1.5x its median daily range, 5-20 points) over a
  six-hour window, and a soak counts as one watering until the soil dries back
  by 3 points. False waterings had been restarting the trend, flashing
  `recently_watered`, and feeding the learner fake cycles (it learned 9 and 10
  cycles where there were 2).
- `recently_watered` now holds for its window from the recorded watering, and a
  watering ends the previous dry run. Previously a reading that dipped a point
  during a soak bounced the status back to `needs_water` with the old dry run.
- Band edges have 2 points of hysteresis and a dry spell must last 30 minutes
  before it raises attention, so a sensor wobbling on the edge no longer flickers
  needs-attention.
- The staying-wet point scales with the dynamic wet limit instead of a fixed 24
  hours.
- Indoor air counts as humid above 80% (was 70%) and very humid above 90%.
- Learned baselines now feed judgments (roadmap Phase 6): time back to range
  sets the pot's own wet allowance; typical rise and peak judge partial
  watering; the learned light norm (per month once known) relaxes the low-light
  threshold so a dark season does not keep a healthy plant flagged; a missing
  habitual grow light is flagged; learned temperature and humidity ranges widen
  the mild bands (never the extremes). The default low-light day is 2500 lx-h,
  which separated dim from normal days in the live data.
- Learning fixes found by the replay: a soak no longer counts as several
  waterings; the typical rise is the cycle's full rise (peak minus the trough
  before the watering), not the rise at the moment of detection; and the span
  before the first watering ever seen is not learned as a post-watering peak.
- Real Open-Meteo indoor daylight response added as a test fixture.

## 0.0.42 - 2026-09-25

Implements the temporal sensor roadmap (`docs/design/temporal_sensor_roadmap.md`)
in full: Phases 1-7 plus the appendix mechanics.

BREAKING: `sensor.<plant>_health` now uses the roadmap's four states only:
`good`, `watch`, `stressed`, `unknown`. The values `needs_water`, `too_wet` and
`too_dry` are gone from Health (they remain Status values). Automations that
matched those on Health need updating. Too-wet soil reads Health `watch`;
prolonged dryness reads `stressed`.

- History foundation (Phase 1). Observations now carry the daylight state in
  force when they were taken. Deduplication considers every signal instead of
  moisture only; previously a light, temperature or humidity change was dropped
  whenever moisture had not moved in the last ten minutes. A heartbeat sample is
  kept every 30 minutes and validity and day/night transitions are always kept.
  The background tick now records observations, as the roadmap requires, so a
  plant with steady moisture keeps coverage instead of drifting to low
  confidence. One compact summary per local day is kept for 30 days.
- Daylight (sections 3 and 8). Sunrise and sunset come from Open-Meteo, then a
  cached forecast up to 48 hours old, then Home Assistant's own sun position,
  then an uncertainty hold. Indoor plants now request sunrise and sunset too.
  Unknown daylight is never treated as night. Air quality has no input.
- Temperature and humidity duration (Phase 3). Continuous time out of range,
  24-hour totals, recovery, rate of change and gaps. Temperature conditions:
  normal, cool, cold, warm, hot, rapid_change, prolonged_cold, prolonged_heat;
  bands are placement-relative. Humidity conditions: normal, dry_air,
  humid_air, prolonged_dry_air, prolonged_humidity. Combined conditions
  cold_wet_condition, accelerated_drying and slow_drying_humid_condition shape
  summaries and health, using the vapor pressure deficit.
- Gated light exposure (Phase 4). Light is judged as lux-hours during daylight,
  not a 24-hour average: previously night readings dragged a well-lit plant
  below the low-light threshold. Night light counts as supplemental only after
  15 continuous minutes, at 60% weight, and a session belongs to the day it
  started even across midnight. Days are classified against Open-Meteo
  radiation (overcast, shaded, supplemental, optimal, adequate, low). Three low
  days raise `insufficient_light` and needs-attention; overcast days are
  forgiven for up to three days; two bright days in a dim spot read as shaded.
  With unknown daylight no light alert can fire.
- Drying coefficient (Phase 2). The wet-duration allowance now follows the
  roadmap's weighted blend of soil trend, temperature, vapor dryness, light and
  bounded outdoor radiation (never more than 15%). The previous evapotranspiration
  branch read the wrong forecast key and never ran. New `sensor_problem`: no
  valid moisture reading for six hours, or a frozen device.
- Soil that is topped up before it ever dries back into range now keeps
  accumulating wet duration. Previously each dip read as "drying" and the next
  watering restarted the wet run, so repeated overwatering never escalated.
- Combined interpretation (Phase 5). One engine combines every signal with the
  roadmap's status precedence, adding `too_cold`, `too_hot`,
  `insufficient_light`, `sensor_problem` and `partial_watering`. Needs-attention
  reasons: soil_dry, persistently_dry, persistently_wet,
  prolonged_temperature_stress, several_days_insufficient_light, sensor_problem.
  New status attribute `temperature_context`.
- Learned baselines (Phase 6). Learning continues after calibration: typical
  watering rise and peak, drying slope, time back to range, normal light and
  supplemental pattern, temperature and humidity ranges, and monthly variation.
  Learned bands are bounded by the care profile, abnormal states are not
  learned, and a placement change now preserves the other placement's baseline
  instead of wiping both.
- Appendix. Dormancy is now evidence-based (a month of low light plus a slightly
  cooler week, or an outdoor plant outside its growing season); it extends the
  wet allowance up to three times and lowers the needs-water threshold.
  Partial watering is detected against the learned typical peak. Soil drying
  far slower than this plant's learned rate is flagged.
- Time-fast-forward tests (Phase 7). All 25 roadmap scenarios run against the
  real engine in `tests/domain/test_timeline.py`, plus the appendix mechanics.
- The temporal store is written only when something durable changes, instead of
  after every one-minute tick.

## 0.0.41 - 2026-09-25

Full-codebase audit. Fixes only; no new features.

- Fixed learned baselines (calibration) being corrupted by a single watering. `detect_watering` returned the newest reading's timestamp for as long as the pre-watering low stayed in its 90-minute window, so one watering was re-stamped on every new reading. The baseline learner closes a cycle whenever the detected watering time changes, so a real sensor reporting every few minutes recorded many fake cycles per watering, with post-watering levels as "troughs". This could satisfy the two-cycle learning gate after one watering and skew the learned band upward. It also anchored `recently_watered` and the cycle peak up to 90 minutes late. Detection now returns the first reading that cleared the rise, which is stable across updates. Existing tests used one reading per watering and could not see this; new tests use realistic dense readings.
- Removed entities left over from earlier releases. Entity keys that newer versions no longer create (for example `calculated_moisture` and `drying_modifier`) stayed in the entity registry as restored "unavailable" entities forever. Setup now prunes registry entries for this config entry whose key is no longer part of the entity contract. Current entities are never touched.
- Fixed a config-entry reload failure. The species image HTTP view was registered on every setup, so a reload (as triggered by the reconfigure flow) tried to register the same route again, and the view kept serving from the previous, unloaded proxy. The view is now registered once per Home Assistant instance and resolves the live proxy per request, answering 404 while the integration is unloaded.
- Moved species image work off the event loop. DNS validation for image URLs, Pillow decoding and resizing, cache writes, and serving cached files ran synchronously on Home Assistant's event loop. They now run in the executor through an injected runner; the pure image module keeps an inline default so it has no Home Assistant dependency.
- The species photo entity now has the entity id `image.<plant>` as documented. It previously registered as `image.<plant>_photo` because the entity name "Photo" was appended to the device name. It is now the device's primary entity (no entity name). An entity already registered as `image.<plant>_photo` keeps its id until renamed in the UI or removed and recreated.
- Added options-flow error messages for the `placement`, `profile`, `species`, and `rain_limit_mm` validation keys. Form selectors currently prevent these from firing, but an untranslated key would render no message, the same failure class as the earlier add-plant loop.
- Removed unused variables in the forecast deriver, and made shipping source plain ASCII: unit strings are written as escapes with identical runtime values, and flow label separators use ASCII.

## 0.0.40 - 2026-09-25

- Removed the hardcoded snake-plant name canonicalization. `enrich_selected` special-cased Dracaena/Sansevieria trifasciata: it injected both names as aliases and then force-overwrote the resolved scientific name to "Dracaena trifasciata" even when no provider could actually resolve it. This was the only per-species logic in the codebase and it behaved inconsistently - one species got a faked accepted name while every other synonym-named plant kept the name iNaturalist returned. Canonicalization now happens generally through the provider chain: iNaturalist may return an older synonym as its active name, Trefle returns the accepted name and lists the synonym, and the chain matches them and adopts Trefle's accepted name. Plants enriched with Trefle configured (the snake plant included) are unchanged; without a resolving provider the name iNaturalist returned is kept as-is rather than invented for one species.

## 0.0.39 - 2026-09-25

- Enrichment now reliably completes when adding a plant. On add, the flow discovers candidates and the user picks one, but `schedule_enrichment` then re-resolved the stored scientific name through iNaturalist and required exactly one candidate to match across scientific name, common name, or matched term. When iNaturalist returned the species alongside an infraspecific taxon (subspecies or variety) that shared the same matched term, that re-match went "ambiguous" and skipped enrichment even though a valid species had been selected. The matcher now prefers an exact scientific-name hit, so a precise binomial resolves to its own taxon and the Trefle/Perenual chain runs.
- iNaturalist supplies the genus out of the box. Its autocomplete response carries no family or genus fields, so a keyless install previously got neither; the genus is now derived from the species binomial (family still requires Trefle). When a Trefle key is present, Trefle's genus still takes precedence.
- Audit confirmation, no change needed: API keys entered in the config flow are written to the entry options, which is exactly where the enrichment chain reads them, so keys on a fresh install reach the providers on first setup.

## 0.0.38 - 2026-09-25

- Fixed the Trefle rate-limit self-regulation shipped in 0.0.37, which never actually engaged. Response headers were looked up with capitalized keys (`RateLimit-Remaining`, `RateLimit-Reset`), but Trefle serves HTTP/2, which lowercases all header names, so the lookup always missed and the gate could only react to a real 429 instead of backing off before one. Response header keys are now normalized to lowercase, so the gate reads `ratelimit-remaining`/`ratelimit-reset` and self-regulates as intended. Confirmed against a live Trefle response (`ratelimit-remaining: 56`). The image proxy already read its headers case-insensitively and was unaffected.
- Verified (no code change needed) that the Trefle species-detail field paths the care parser reads - `growth.light`, `growth.atmospheric_humidity`, `growth.soil_humidity`, `growth.ph_minimum`/`ph_maximum`, `growth.minimum_temperature.deg_c`/`maximum_temperature.deg_c`, `specifications.growth_habit`/`growth_rate`/`toxicity`/`average_height.cm`, and top-level `duration`/`edible` - match the live detail response shape.

## 0.0.37 - 2026-09-24

- Richer Trefle enrichment. After iNaturalist confirms a species, the chain now follows the Trefle match to its species detail endpoint and pulls the growth and care record: `light_requirement`, `humidity_requirement`, `soil_moisture_requirement` (Trefle 0-10 scales), `ph_minimum`, `ph_maximum`, `minimum_temperature_c`, `maximum_temperature_c`, `growth_habit`, `growth_rate`, `toxicity`, `average_height_cm`, `duration`, and `edible`. These appear as attributes on the species sensor; fields Trefle lacks for a species are omitted. The Trefle search response only carries taxonomy and an image, so the detail fetch is what makes this data available.
- Rate-limit self-regulation for Trefle. Every Trefle response's `RateLimit-Remaining` and `RateLimit-Reset` headers are read through a small gate that stops issuing Trefle requests once the window is spent and resumes at the reported reset time, so bursts (for example re-enriching many plants on startup) back off before hitting Trefle's 60-requests-per-minute limit instead of absorbing 429s.
- Resilient chaining. A Trefle or Perenual failure (rate limit, auth, or network) during enrichment now skips only that provider instead of discarding the whole result, so the confirmed iNaturalist identity, taxonomy, and photo survive a secondary provider outage.

## 0.0.36 - 2026-09-24

- Added a dedicated `image.<plant>` entity for the species photo. It serves the already-cached, sanitized WebP through Home Assistant's own image proxy, so the photo renders natively as the entity picture and updates automatically when a new photo is fetched. The entity is unavailable until a photo has been resolved for that plant, and is removed with the plant. This adds the IMAGE platform alongside the existing sensor and binary_sensor platforms.
- The species sensor's `image_url` attribute is unchanged and still points at the same cached image, so existing custom cards keep working; the new entity and the attribute are two views of one cached photo, not a second download.

## 0.0.35 - 2026-09-24

- Fixed species photos failing to decode (the image proxy logged `Species image could not be fetched ... : image`). The downloader read the HTTP body with a single `StreamReader.read(n)` call, which returns only the bytes currently buffered rather than the whole body, so any image delivered in more than one network chunk arrived truncated and Pillow refused to decode it. The downloader now accumulates chunks up to the size cap, so the complete image is read; oversized bodies still stop early and are refused by the length check. This was the actual cause of missing species images: the enrichment and the iNaturalist v1 photo URL were correct all along, but the fetched bytes were incomplete.

## 0.0.34 - 2026-09-24

- Fixed a thread-safety defect that raised a RuntimeError roughly once a minute and left a `coroutine 'PlantHelperRuntime.evaluate' was never awaited` warning in the log. The background temporal tick and the daily image-cache cleanup were plain synchronous functions handed to `async_track_time_interval`, so Home Assistant ran them in an executor thread, where `hass.async_create_task` is not allowed. Both are now decorated with `@callback` (matching the weather tick) so they run on the event loop. Besides ending the log spam this restores background re-evaluation: durations and drying were not advancing between sensor updates because every tick aborted before scheduling any work.
- Species image fetch failures now log at warning level with the specific reason (for example `http_403`, `ssrf`, `redirect_limit`, `image_format`) instead of only at debug, so a missing species photo is diagnosable from the normal log without enabling debug logging.

## 0.0.33 - 2026-09-24

- Fixed species photos silently never appearing. The image proxy rejected a download unless its HTTP `Content-Type` header was exactly `image/jpeg`, `image/png`, or `image/webp`. Image hosts (iNaturalist open-data on S3, provider thumbnail CDNs) routinely serve real photos as `application/octet-stream` or with no type at all, so a valid image was dropped and the `image_url` attribute never attached to the species sensor. The proxy now validates the actual decoded image format (magic bytes via Pillow) instead of trusting the header, which is both safer (the bytes are parsed) and compatible with mislabeled sources. Size, dimension, pixel, and decompression-bomb limits are unchanged.
- When an image still cannot be fetched, the debug log now records the specific reason (for example `http_403`, `ssrf`, `image_format`, or `size`) instead of a generic failure, so the cause is diagnosable by enabling debug logging for `custom_components.plant_helper`.

## 0.0.32 - 2026-09-24

- Config-flow bug fixes and hardening after a report that adding a plant looped back to the sensor step after matching a species.
- Fixed the root cause of that loop: add-plant validation errors were shown as `errors={error_key: "invalid"}`, which used the error key as a form field name and the literal `"invalid"` as the message. `"invalid"` only exists under `config.error`, not `options.error`, so a real failure (for example a moisture sensor that was momentarily unavailable) rendered no visible error and silently re-displayed the sensor form. Errors are now attached to `base` with their real translation key, so the actual reason is shown. The edit flow had the same mis-keying and is fixed the same way.
- Relaxed the moisture readiness gate on add and edit: a transiently unavailable sensor no longer blocks the operation (the plant simply waits for data, as the temporal engine already handles). A non-numeric or out-of-range reading still fails, but now with a clear message instead of a silent loop.
- Fixed a separate data-loss bug: editing a plant wiped its species. The edit form has no species field, so the normalized config dropped species (and with it enrichment and the species photo) on every edit. The stored species is now preserved when the form does not supply one.
- Hardened plant-set notifications so a single failing entity-platform callback can no longer abort the collection mutation (add, update, or remove) that triggered it; the failure is logged and the operation completes.
- Corrected the README license section: it still claimed no license was included, but the MIT LICENSE file is present. It now points to LICENSE.

## 0.0.31 - 2026-09-23

- Documentation pass. Rewrote the user-facing docs (README, ENTITIES, INSTALLATION, SERVICES, TROUBLESHOOTING) to be concise and accurate: they still described pre-temporal behavior and were wrong on several points. Corrected the status vocabulary and its attributes (confidence, drying_context, light_context, humidity_context, dormant, since), the calibration entity (now learning / calibrated, not source_sensor), the wired species photo, and the up-to-nine-sensor entity set. No code change.
- Removed stale cruft from the maintainer docs: the fixed 0.0.1 tag reference and the per-patch "maintenance outcome" notes that had accumulated in the forward-looking maintenance plan.
- Left the internal design docs and the dated lifecycle audit as historical records rather than rewriting past snapshots.

## 0.0.30 - 2026-09-23

- Seasonal dormancy (F4): a dormant plant now tolerates wet soil longer instead of being nagged. Dormancy is read from signals already computed per plant (outdoor `growth_season`, indoor `season` / `day_length`) and applied as a multiplier on the drying coefficient, so a resting plant's tolerated wet period lengthens through the existing coefficient machinery rather than a parallel path. The new `dormant` attribute on `sensor.<plant>_status` shows when a plant is being judged as dormant, and `drying_context` reflects the slower expected drying.
- Two deliberate safety bounds: the seasonal effect is clamped like the drying coefficient, so extreme waterlogging still escalates to too_wet even in deep dormancy; and dormancy relaxes only the wet (overwatering) side, which is the real dormancy-season risk. A genuinely dry plant still reads needs_water in any season, so a resting plant is never left to go thirsty.
- Implementation note vs the roadmap: dormancy adjusts the wet allowance rather than also widening needs_water patience, because suppressing a real dryness signal in winter is the more dangerous failure. This is the safer reading of the roadmap intent.
- This completes the F1-F4 feature roadmap (species photos, light and humidity tracking, learned per-plant baselines, seasonal dormancy).

## 0.0.29 - 2026-09-23

- Learned per-plant baselines (F3): each plant now learns its own comfortable moisture range from how it actually behaves, and once calibrated the engine judges against that instead of the generic profile band. A plant that likes it wet can read needs_water at 38% while another reads wet at the same value; the profile becomes the seed and fallback, not the law.
- How it learns: the new `domain/temporal/baseline.py` accumulates the troughs a plant is allowed to reach before watering and the peaks it reaches just after, across watering cycles. Calibration completes only after 14 days of coverage with at least two full cycles at high confidence, and the learned band is clamped so a stuck or noisy sensor can never teach a nonsense range. Accumulated samples and the finished baseline persist through the existing store and survive restarts.
- The `sensor.<plant>_calibration` entity now reports `learning` while it gathers evidence and `calibrated` once the learned band is in effect (previously it reported `source_sensor`). This is the indicator of whether a plant is judged by its learned range or the profile.
- Moving a plant (placement change) or changing its species to a different taxon relearns the baseline; an alias species change keeps it.
- Roadmap deviation, noted: persistence uses the existing `PlantHelperStorage` learned/active-samples layer (which was already built for exactly this) rather than bumping the temporal store to v2, avoiding a duplicate store. The whole learning path is defensively wrapped: any learning failure falls back to the profile band, so the core evaluation cannot break.

## 0.0.28 - 2026-09-23

- Light and humidity tracking (F2): light and humidity now get the same trend-aware treatment as soil moisture, for both indoor and outdoor plants. Each is judged on a rolling mean (a day-long window for light, a shorter one for humidity) and reported as low / adequate / high in the new `light_context` and `humidity_context` attributes on `sensor.<plant>_status`.
- Sustained inadequate light or humidity now lifts `sensor.<plant>_health` to `watch`, but never raises needs_attention: moisture remains the only signal that flags a plant for action, and a moisture alarm (or a missing moisture reading) always wins over the secondary signals. Verdicts only form once enough valid samples exist, so a sparse sensor never drives them.
- `PlantObservation` now carries light and humidity alongside moisture and soil temperature in the one rolling history per plant, and they persist and restore through the temporal store.
- Implementation note vs the roadmap: light adequacy uses a rolling mean rather than a per-local-day integral. The integral would pull timezone/local-day handling in for marginal benefit in this first cut; the low/adequate/high outcome is identical. The `DailySummary` scaffold remains for a later integral-based refinement.

## 0.0.27 - 2026-09-23

- Added a feature roadmap (`docs/design/feature_roadmap.md`) that pre-decides the design of the next four features (species photos, light and humidity tracking, learned per-plant baselines, seasonal dormancy) so each can be built without re-litigating decisions.
- Species photos (F1): wired the existing security-hardened image proxy end to end. `sensor.<plant>_species` now shows a real photo via its `image_url` attribute, served from a local authenticated endpoint (`/api/plant_helper/image/<digest>`) rather than a raw provider URL. The proxy fetches, SSRF-validates, thumbnails to WEBP, caches, and serves the image; enrichment triggers the refresh, and a daily timer garbage-collects unreferenced thumbnails.
- On any image failure the raw provider URL is deliberately never surfaced; the plant simply shows no photo until the next successful refresh. The image endpoint requires authentication.
- No behavior change to any existing entity state; this only populates the previously reserved `image_url` attribute.

## 0.0.26 - 2026-09-23

- Removed the dead parallel flow architecture: `domain/setup_flow.py`, `domain/options_flow.py`, and `domain/reconfigure_flow.py`, plus their `tests/domain/test_flows.py`. These were pure, tested flow models that nothing wired: the live config flow is `config_flow.py` and the live options flow is `options.py` (which `config_flow` actually imports). They were dead and tested at once, which only gave false confidence about code that never ran.
- Removed two runtime dataclass fields that were never assigned or read: `learning` and `species_image_proxy`. The `learning.py` and `image_proxy.py` modules stay as scaffolding for the deferred learned-baselines and species-image features; only the dead placeholder slots are gone.
- No behavior change. `placement.py` and `runtime.handle_placement_change` were audited and kept: `placement.py` drives the edit-plant placement transition, and the hook is a deliberately empty wired stub, not dead code.

## 0.0.25 - 2026-09-23

- Fixed the status entity so it delivers context to both indoor and outdoor plants, which is what it was in the design for. `sensor.<plant>_status` now always carries `summary`, `reason`, `since`, `confidence`, `drying_context`, and `placement`, regardless of whether weather is configured. Outdoor plants additionally get `rain_suppression`, `frost_hours`, and `exposure`; indoor plants get `external_daylight`. Irrelevant attributes are dropped per plant rather than gating the whole set.
- Root cause of the 0.0.20 implementation being weak for indoor plants: the context was gated on a forecast being present and `drying_context` was computed only from the outdoor forecast, so indoor plants (which have no forecast) got almost nothing. `drying_context` is now derived from the temporal engine's drying coefficient, which is computed for both placements (evapotranspiration outdoor, soil temperature and humidity indoor), so the same word means the same thing on any plant. `confidence`, which the engine computes for every plant, is now surfaced too.
- This supersedes the 0.0.24 narrowing of the status entity to three attributes. The compact core (`summary`/`reason`/`since`) is kept and extended with the signals that are meaningful for every plant, and raw engine internals (drying rate, cycle peak, adjusted limit) still stay out of attributes.

## 0.0.24 - 2026-09-23

- Added the environmental drying coefficient (`domain/temporal/drying.py`). The wet-duration limit that decides `too_wet` is now scaled by expected drying instead of a flat 72 hours: fast-drying conditions shorten the allowance and slow-drying conditions extend it, bounded so a prediction can never shorten it by more than 35% or extend it by more than 100%. Outdoor plants are driven primarily by Open-Meteo reference evapotranspiration (`et0_24h`); indoor plants fall back to soil temperature and humidity. The persisted `adjusted_wet_duration_limit` records the limit actually used.
- The realized moisture slope still overrides the prediction: a soil that is measurably draining reads `drying` regardless of how aggressively conditions say it should have dried, so a shortened limit never overrules real drainage. All coefficients are starting values to tune against fixtures.
- Narrowed the status entity to the roadmap's compact attribute set: `sensor.<plant>_status` now exposes only `summary`, `reason`, and `since`, and no raw temporal state leaks into attributes. Status precedence is a single deterministic ordering in `domain/temporal/status.py`, and `needs_attention` is exactly the attention set of the status.
- BREAKING: this removes the weather attributes added to `sensor.<plant>_status` in 0.0.20 (`placement`, `rain_suppression`, `drying_context`, `frost_hours`, `exposure`, `external_daylight`). The weather still drives the status itself (outdoor rain still produces `watering_paused`); only the informational attributes are gone. If you want that context back on an entity, it belongs on a dedicated diagnostic sensor rather than cluttering the status.

## 0.0.23 - 2026-09-23

- Added persistence for the temporal soil engine. Rolling observations and moisture state now live in their own Home Assistant store (`plant_helper.temporal.<entry>`), separate from the config store. Writes are coalesced and debounced (flushed on a timer and on unload) rather than one write per reading. On restart the store is restored with timestamp validation: observations with a missing, naive, unparseable, or future timestamp are dropped, and state timestamps failing the same check reset to empty so duration timing resumes cleanly instead of trusting a bad clock. Restored data is pruned to plants that still exist.
- A run that predates the retained observation window still ages correctly: the persisted run start survives restart and window pruning, so a plant that was wet for days before a restart escalates rather than resetting to a fresh reading.
- Added a background evaluation tick (default 60 s, decoupled from the weather timer) that advances durations while moisture is unchanged. This is what makes `staying_wet` and `too_wet` reachable without waiting for the next sensor push. The tick records no observation and makes no provider or weather request, and it only notifies entities when the user-facing status actually changes.
- Removed `domain/storage_revision.py` and its re-exports. Its helpers had no call sites (plant-config concurrency is handled inline in `domain/storage.py`, which defines the `StorageConflictError` actually used), so this is dead-code removal, not a behavior change.

## 0.0.22 - 2026-09-23

- Introduced the temporal soil engine (`domain/temporal/`): a pure, clock-injected moisture interpreter that replaces the static per-reading band check. `sensor.<plant>_status`, `sensor.<plant>_health`, and `binary_sensor.<plant>_needs_attention` are now driven by an observation history and a wet/dry state machine rather than a single instantaneous reading. Raw measurement entities are unchanged.
- Fixed the long-standing false alarm where one elevated reading on a dry-profile plant (for example 47% against a 15-45 band) immediately read `too_wet`. A single elevated reading now reads `wet` with good health and no attention; escalation to `too_wet` requires sustained wetness beyond the drying limit with sufficient confidence. Rain suppression still folds in for outdoor plants, and critically dry soil still overrides it.
- BREAKING: the status string `water_soon` is renamed to `needs_water`. New status strings are also introduced (`recently_watered`, `wet`, `staying_wet`, `too_wet`, `drying`, `approaching_dry`, `too_dry`, and `waiting_for_data`), while `normal` and `watering_paused` are retained. Grep your automations and dashboards for `water_soon` before upgrading.
- Consolidated the test suite from 34 files into 10 foundational modules to keep the upload file count down, preserving the behavioral, structural, and packaging coverage.

## 0.0.21 - 2026-09-23

- Maintenance release. No runtime behavior change.
- Removed source-string snapshot tests that asserted implementation text rather than behavior and would break on any refactor. Kept and consolidated the behavioral, structural, and packaging checks. Manifest version is now validated only for self-consistency against the changelog, so a release bump touches one place instead of several.
- Added `docs/design/execution_roadmap.md`: a sequenced plan from the current release toward the full design, so temporal-sensor work and the remaining enrichment work proceed in order rather than scattered.

## 0.0.20 - 2026-09-23

- Wired Open-Meteo into the runtime. The forecast and air-quality collectors now run against the live Open-Meteo Forecast and Air Quality APIs through a new HTTP client and response adapter, so the previously unused collectors are connected.
- Added a periodic weather coordinator keyed off the configured update interval and the canonical coordinates (Plant Helper override or Home Assistant location). Forecast and air-quality caches self-throttle and refresh independently; a plant census decides whether the outdoor forecast and air-quality requests run.
- Plant evaluation now consumes the cached environment. Indoor plants use external daylight and seasonal context; outdoor plants gain rain suppression, drying context, frost, and exposure context. Physical moisture stays authoritative and critically dry soil still recommends watering regardless of forecast rain.
- The `sensor.<plant>_status` entity now exposes weather-derived attributes (placement, and for outdoor plants rain suppression, drying context, frost hours, and exposure; external daylight for indoor plants) when a forecast is available.

## 0.0.19 - 2026-09-23

- The species sensor now publishes the merged enrichment result. The iNaturalist to Trefle to Perenual chain already resolved identity and care data, but the entity only exposed the scientific name and family. The `sensor.<plant>_species` entity now also exposes common name, genus, watering category, and sunlight requirements as attributes when the providers return them.
- No change to the state value (the resolved scientific name), entity IDs, unique IDs, units, device classes, or storage schema. Provider, provenance, and other diagnostic fields remain internal.

## 0.0.18 - 2026-09-23

- Plant add, edit, and remove no longer overwrite global options with an empty set. The plant-management flow now returns the current options unchanged, so latitude, longitude, provider credentials, access level, and update interval survive plant changes.
- Plant management no longer triggers a full config-entry reload. Removed the entry update listener that reloaded on every options write; global reconfigure still reloads exactly once through the config flow.
- Stopped exposing raw third-party species image URLs as an entity attribute. The species entity no longer publishes a provider hotlink; the local authenticated image path remains reserved in the entity contract for a future release.
- Hygiene: replaced the star import in the config flow with explicit names, computed the entity unique ID once through the domain helper, and removed unused imports in the options, config, and storage modules.

## 0.0.17 - 2026-09-22

- Completed credential-aware provider activation and confirmed snake-plant alias resolution.
- Added provider request single-flight handling and updated enrichment cache policy constants.
- Preserved entity IDs, storage contracts, field-level provenance, and local image proxy behavior.

## 0.0.17 - 2026-09-22

- Removed the separate species input from plant setup.
- Use the plant name as the common-name lookup sent to iNaturalist.
- Show candidate selection when several species match and store the selected scientific identity internally.
- Accept exact scientific-name matches during later provider enrichment.

## 0.0.15 - 2026-09-22

- Removed the obsolete Home Assistant ozone sensor selector from setup and options.
- Made Open-Meteo the sole ozone source using the configured coordinates.
- Retained compatibility with existing entries by ignoring any legacy `ozone_entity` option.

## 0.0.14 - 2026-09-22

- Resolve the optional plant name as a common name during add-plant setup.
- Show a species-selection step when iNaturalist returns multiple candidates, then store the selected scientific identity.
- Keep the configured common-name fallback available while provider resolution runs or fails.
- Reorganize tests by subsystem instead of keeping every regression and release check in the test root.

## 0.0.13 - 2026-09-22

- Added the chained species-provider workflow: iNaturalist common-name discovery, Trefle taxonomy resolution, and Perenual care-data fallbacks.
- Preserved resolved species context across later sensor evaluations and refreshed stored plants during startup.
- Reloaded the integration when global provider options change.
- Added recorded provider fixtures and regression tests for empty, ambiguous, synonym, and multiple-candidate responses.

## 0.0.12 - 2026-09-22

- Added a humidity entity for each plant with a configured humidity source.
- Added a battery entity that preserves verified categorical states (`high`, `middle`, `low`) or numeric values from 0 through 100.
- Improved the calibration entity so it clearly reports `source_sensor` instead of implying that setup was incomplete.
- Replaced the meaningless calibration progress value with a concise explanation that Plant Helper uses the selected source sensor's calibrated reading.
- Preserved all existing entity keys and added the new entities without renaming or replacing existing entities.
- Added regression coverage for the humidity contract, mixed battery contract, calibration meaning, and entity-key preservation.

## 0.0.11 - 2026-09-22

- Fixed Home Assistant entity setup crashes caused by assigning Plant Helper's internal `EntityContract` as `entity_description`.
- Kept the internal contract separate while continuing to apply names, icons, units, device classes, and state classes directly to entities.
- Prevented plant-device deletion while any entity-registry record, including a template entity, still references the device.
- Restricted categorical battery states to the verified `high`, `middle`, and `low` values while retaining numeric values from 0 through 100.
- Added regressions for Home Assistant entity-description compatibility, referenced-device retention, and the exact battery state contract.

## 0.0.10 - 2026-09-22

- Fixed the battery-source regression introduced by restricting the selector to numeric battery device-class sensors.
- Restored support for soil sensors that expose categorical battery states such as `middle`.
- Preserved numeric battery percentages as numbers and categorical battery states as source values without inventing percentages.
- Kept unavailable, unknown, empty, and unsupported battery values unavailable.
- Added fixture-backed regression tests for both real soil-sensor battery formats.

## 0.0.9 - 2026-09-22

- Reworked add, edit, and remove lifecycle handling around durable storage commits.
- Fixed removal failures caused by post-commit entity and registry cleanup being reported as if the plant still existed.
- Added idempotent removal cleanup with persisted progress and automatic retry during integration setup.
- Moved removal ownership into the runtime lifecycle coordinator instead of the options form.
- Removed loaded entities safely, including entities still waiting to be attached by Home Assistant.
- Scoped entity-registry cleanup to the current config entry and exact plant unique-ID prefix.
- Required the removal confirmation checkbox and handled empty plant lists.
- Prevented post-commit add and edit activation failures from producing false save-failure messages.
- Added lifecycle foundation tests for durable removal, retry after restart, confirmation, and setup ordering.

## 0.0.8 - 2026-09-22

- Fixed Add Plant reporting failure after the plant had already been persisted and created.
- Prevented newly queued entities from writing state before Home Assistant has attached them to the entity platform.
- Restricted the soil-moisture selector to moisture sensors and the battery selector to numeric battery sensors.
- Added regression coverage for the asynchronous entity-creation race observed in Home Assistant.

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
