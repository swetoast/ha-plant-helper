# Plant Helper Temporal Sensor Roadmap

## Status

Approved implementation roadmap

## Development baseline

Plant Helper `0.0.17`

## Purpose

This roadmap changes Plant Helper from immediate threshold reactions into time-based plant monitoring using moisture, light, temperature, and humidity.

Open-Meteo supplies bounded environmental context, including sunrise, sunset, daylight duration, solar radiation, and weather conditions. Local physical sensors remain authoritative for the plant's actual microclimate.

External species-provider changes are outside the scope of this roadmap. The existing provider implementation remains untouched.

---

# 1. Scope and compatibility contract

## In scope

- Moisture history and watering cycles
- Temperature exposure duration
- Humidity exposure duration
- Natural and supplemental light exposure
- Open-Meteo sunrise, sunset, radiation, and weather context
- Plant-specific temporal summaries
- Persistent but compact historical state
- Restart-safe evaluation
- Time-fast-forward regression tests

## Out of scope

- External species-provider changes
- New public entities
- Entity ID changes
- Device identity changes
- Broad care-profile redesign
- Raw history in entity attributes
- Exposing internal coefficients or confidence calculations

## Compatibility requirements

The implementation must preserve:

- Existing config entry
- Existing plant UUIDs
- Existing device identifiers
- Existing entity IDs
- Existing unique IDs
- Existing measurement entities
- Existing units
- Existing device classes
- Existing state classes
- Existing plant CRUD behavior
- Existing provider behavior
- Existing Home Assistant setup and unload behavior
- Independent histories for plants that share the same display name

---

# 2. Core design principles

## Physical sensors remain authoritative

Local sensors define the plant's actual microclimate:

```text
soil moisture
soil temperature
air humidity
illuminance
```

Open-Meteo supplies context:

```text
sunrise and sunset
daylight duration
outdoor shortwave radiation
cloud and weather context
outdoor temperature and humidity context
```

Open-Meteo cannot override a valid local reading.

## Time determines meaning

A measurement and a condition are not the same thing.

```text
Moisture: 47%
```

is a current observation.

```text
Status: wet
```

is a current interpretation.

```text
Health: watch
Reason: persistently_wet
```

requires evidence accumulated over time.

## Uncertainty suppresses escalation

If history, daylight boundaries, or source readings are insufficient:

- Continue showing valid physical measurements.
- Avoid escalating health.
- Keep `Needs attention` off unless another reliable condition requires action.
- Report a neutral or provisional status internally.
- Resume evaluation when sufficient evidence returns.

---

# 3. Solar bounding and artificial-light architecture

```text
ForecastCollector / Home Assistant Sun
                |
                v
Sunrise-to-sunset daylight window?
        |                       |
       Yes                      No
        |                       |
Local lux above threshold?   Local lux above threshold
        |                    and duration gate passed?
        |                       |
Natural exposure          Supplemental exposure
        |                       |
        |                 Apply source weighting
        |                       |
        +-----------+-----------+
                    |
                    v
       effective_light_exposure
```

## Collector isolation

Daylight classification depends on the Forecast collector and Home Assistant's solar ephemeris.

```text
ForecastCollector failure
→ cached sunrise and sunset
→ Home Assistant Astral fallback
→ uncertainty hold
```

The Air Quality collector is isolated:

```text
Air Quality failure
→ ozone context unavailable
→ zero effect on sunrise, sunset, daylight classification, or light accumulation
```

---

# 4. Phase 1: Time-series history foundation

## Objective

Create one compact, independent temporal record for every plant UUID.

Two plants with the same display name must retain separate histories.

## Observation model

```python
@dataclass(frozen=True, slots=True)
class PlantObservation:
    observed_at: datetime
    moisture: float | None
    temperature: float | None
    humidity: float | None
    illuminance: float | None

    moisture_valid: bool
    temperature_valid: bool
    humidity_valid: bool
    illuminance_valid: bool

    is_daylight: bool | None
    daylight_source: str
    forecast_generation: int | None
```

`is_daylight` uses three states:

```text
true
false
unknown
```

An unknown daylight classification must not be treated as nighttime.

## Collection triggers

Record and evaluate when:

- A configured physical sensor changes materially
- The 350 ms debounce window completes
- A periodic background tick occurs
- A new Forecast snapshot becomes available
- Sunrise or sunset is crossed
- The integration starts
- A plant's configured physical source changes

## Dual tick system

### Event-driven tick

Physical sensor changes trigger immediate local evaluation after the existing 350 ms debounce.

### Background interval tick

A periodic tick advances duration-based states even when physical values remain unchanged.

The background tick must not trigger unnecessary provider or weather requests.

## Sample retention

### Rolling observations

Used for immediate gradients and durations:

```text
Recommended horizon: 48 hours
Bounded number of samples
```

### Daily summaries

Used for multi-day interpretation:

```text
Recommended horizon: 30 days
One compact record per local day
```

Do not persist every sensor event indefinitely.

## Sample deduplication

Do not append a new observation when:

- Values are unchanged
- Only irrelevant attributes changed
- The timestamp interval is too short to add analytical value
- The same unavailable state has already been recorded

Always record meaningful transitions:

```text
valid → unavailable
unavailable → valid
normal → sharp moisture rise
daylight → nighttime
nighttime → daylight
```

## Restart behavior

On startup:

1. Restore rolling state and daily summaries.
2. Read the latest configured physical states.
3. Restore the latest usable Forecast snapshot.
4. Establish the current daylight window.
5. Avoid immediate status escalation from one restored sample.
6. Resume duration timing from persisted evidence only when timestamps are valid.

## Phase 1 acceptance criteria

- Both plants with the same name maintain isolated histories.
- Identical values do not cause excessive writes.
- Valid zero values are preserved.
- Invalid readings do not enter gradients or averages.
- A restart does not reset active duration tracking.
- Missing Open-Meteo does not stop physical data collection.
- No existing public entity contract changes.

---

# 5. Phase 2: Moisture-cycle temporal engine

## Objective

Replace immediate wet and dry threshold reactions with watering-cycle interpretation.

## Moisture states

```text
normal
recently_watered
wet
drying
approaching_dry
needs_water
staying_wet
too_wet
too_dry
sensor_problem
```

## Watering-event detection

A watering event requires a meaningful positive moisture change over a bounded interval.

Conceptually:

```text
moisture rise >= watering-rise threshold
within watering-detection window
with valid readings before and after
```

A change such as:

```text
39% → 47%
```

may be classified as probable watering.

Noise such as:

```text
46% → 47% → 46%
```

must not create watering events.

## Wet-state progression

```text
moisture enters upper range
→ wet

sharp rise detected
→ recently_watered

moisture decreases meaningfully
→ drying

moisture remains elevated without sufficient decline
→ staying_wet

wetness persists beyond adjusted duration
→ too_wet
```

## Dry-state progression

```text
moisture approaches lower range
→ approaching_dry

moisture remains below lower threshold
→ needs_water

dryness remains unresolved for excessive duration
→ too_dry
```

## Current live example

A plant reporting `47%` should initially become:

```text
Moisture: 47%
Status: wet
Health: good
Needs attention: off
```

If moisture falls normally:

```text
Status: drying
Health: good
Needs attention: off
```

Only sustained excessive wetness should produce:

```text
Status: too_wet
Health: watch
Needs attention: on
Reason: persistently_wet
```

---

# 6. Balanced indoor drying coefficient

## Objective

Adjust temporal expectations using local microclimate measurements while keeping outdoor radiation bounded.

Raw values must be normalized before weighting. The coefficient must not directly combine degrees Celsius, relative humidity, lux, radiation, and moisture slope.

```python
k_drying = clamp(
    0.40 * normalized_moisture_slope
    + 0.20 * normalized_local_temperature
    + 0.15 * normalized_vapor_dryness
    + 0.10 * normalized_local_light
    + 0.15 * bounded_outdoor_radiation,
    0.0,
    1.0,
)
```

## Weight allocation

```text
Local moisture trend:      40%
Local temperature:         20%
Local humidity context:    15%
Local illuminance:         10%
Outdoor radiation context: 15% maximum
```

## Inputs

```text
normalized_moisture_slope
→ observed local drying trend

normalized_local_temperature
→ profile-relative temperature context

normalized_vapor_dryness
→ inverse humidity context, bounded by local temperature

normalized_local_light
→ local illuminance exposure

bounded_outdoor_radiation
→ contextual Open-Meteo contribution, capped at 15%
```

## Dynamic wet-duration limit

Start from a conservative profile limit:

```text
base_wet_duration_limit
```

Then adjust using environmental context:

```text
high expected drying
→ shorter persistence allowance

low expected drying
→ longer persistence allowance
```

The adjustment remains bounded:

```text
minimum: no more than 35% shorter
maximum: no more than 100% longer
```

## Critical safety rule

`k_drying` adjusts when Plant Helper expects drying. It does not override observed moisture behavior.

If the actual moisture slope shows that the soil is drying normally, the realized trend is more important than predicted drying conditions.

## Environmental context model

```python
@dataclass(frozen=True, slots=True)
class EnvironmentalDryingContext:
    k_drying: float
    local_moisture_slope: float | None
    outdoor_radiation_bounded: float | None
    adjusted_wet_duration_limit: float
    confidence: str
```

## Phase 2 acceptance criteria

- A single elevated reading does not trigger `too_wet`.
- Probable watering produces `recently_watered`.
- A declining moisture trend produces `drying`.
- Persistent wetness requires duration evidence.
- Low expected drying extends the wet-duration allowance.
- Strong expected drying shortens the allowance conservatively.
- Health and attention do not react immediately to one sample.

---

# 7. Phase 3: Temperature and humidity duration tracking

## Temperature states

Internal conditions:

```text
normal
cool
cold
warm
hot
rapid_change
prolonged_cold
prolonged_heat
```

A brief excursion affects current interpretation but not long-term health.

Example:

```text
23 °C → 17 °C briefly
→ cool

17 °C for a prolonged period
→ prolonged_cold
```

## Humidity states

Internal conditions:

```text
normal
dry_air
humid_air
prolonged_dry_air
prolonged_humidity
```

## Duration rules

Track:

- Continuous time outside range
- Total exposure during the previous 24 hours
- Repeated daily exposure
- Recovery duration
- Rate of change
- Measurement gaps

## Combined conditions

### Cold and wet

```text
soil remains wet
+ local temperature remains low
+ actual drying slope is weak
→ cold_wet_condition
```

### Warm and dry

```text
soil moisture falling
+ temperature elevated
+ local humidity low
→ accelerated_drying
```

### Warm and humid

```text
temperature elevated
+ humidity elevated
+ moisture remains high
→ slow_drying_humid_condition
```

These conditions influence timing and summaries. They must not become separate public entities.

## Phase 3 acceptance criteria

- Brief temperature and humidity excursions do not alter health.
- Persistent exposure can change health to `watch`.
- Recovery clears the condition after a stable return period.
- Cold and wet conditions influence moisture interpretation.
- Warm and dry conditions explain accelerated drying.
- Missing optional sensors reduce confidence without breaking moisture monitoring.

---

# 8. Phase 4: Gated light-exposure engine

## Objective

Evaluate cumulative light across proper solar windows while treating natural and supplemental sources separately.

## Daylight calculation

Use the fallback chain:

```text
1. Open-Meteo Forecast sunrise and sunset
2. Cached Forecast ephemeris, valid for up to 48 hours
3. Home Assistant location and Astral calculation
4. Uncertainty hold
```

Air Quality collection remains completely isolated:

```text
Air Quality failure
→ ozone context unavailable
→ no impact on daylight calculations
```

## Natural exposure

During sunrise-to-sunset:

```text
local lux × elapsed hours
→ natural_light_exposure
```

Nighttime darkness is excluded from natural exposure.

## Supplemental exposure

Outside sunrise-to-sunset:

```text
local lux above threshold
+ maintained for minimum duration
→ supplemental session
```

Recommended initial duration gate:

```text
15 continuous minutes
```

Short room-light events are ignored.

## Internal units

When the source is lux:

```text
lux-hours
```

Do not call this DLI.

True DLI is calculated only with:

- A calibrated PPFD sensor, or
- A future explicitly configured source profile with a documented conversion

## Lux-hour accumulation

```text
lux_hours = Σ(lux × sample_duration_hours)
```

## Artificial-light weighting

```text
Calibrated PPFD:
  weight = 1.00
  confidence = high

Known broad-spectrum profile:
  profile-defined weight
  confidence = medium

Unknown source with lux only:
  conservative weight between 0.50 and 0.75
  confidence = low

Below duration gate:
  weight = 0.00
```

For the first implementation, use one documented conservative internal default for unknown artificial sources:

```text
weight = 0.60
```

The value remains internal and testable.

## Effective exposure

```python
effective_light_exposure = (
    natural_light_exposure
    + artificial_light_exposure * artificial_weight
)
```

## Cross-midnight sessions

A continuous supplemental-light session maintains one session identity.

Example:

```text
20:00 → 02:00
```

The engine stores time-indexed segments but associates the complete photoperiod with the day on which the session started.

## Solar and local-light interpretation

### High outdoor radiation and low local lux

```text
classification: shaded_or_obstructed
```

Require persistence before affecting health:

```text
minimum evidence: 48 hours or two daylight periods
```

### Low outdoor radiation and low local lux

```text
classification: overcast_day
```

Suppress an insufficient-light warning for up to three consecutive days, provided poor outdoor conditions explain the low exposure.

### Nighttime and sustained local lux

```text
classification: supplemental_light_detected
```

Accumulate weighted artificial exposure.

### High outdoor radiation and high local lux

```text
classification: optimal_natural_exposure
```

## Daily light exposure model

```python
@dataclass(frozen=True, slots=True)
class DailyLightExposure:
    day_date: str
    daylight_start: datetime | None
    daylight_end: datetime | None
    daylight_classification_certain: bool

    natural_light_exposure: float
    artificial_light_exposure: float
    effective_light_exposure: float

    artificial_weight_applied: float
    confidence: str
    classification: str

    daily_peak_lux: float
    valid_coverage_hours: float
    mean_outdoor_radiation: float | None
```

## Phase 4 acceptance criteria

- Nighttime zero lux does not reduce daylight exposure.
- Brief room-light events are ignored.
- Sustained nighttime light is accumulated separately.
- Unknown artificial light is not counted 1:1.
- Cross-midnight sessions remain intact.
- Overcast days do not immediately produce warnings.
- Bright outdoor conditions with consistently low indoor lux can identify likely shading.
- Forecast failure falls back without false light alerts.

---

# 9. Phase 5: Combined interpretation and summaries

## Status priority

The engine selects one primary status using explicit precedence.

Recommended order:

```text
sensor_problem
needs_water
too_dry
too_wet
staying_wet
recently_watered
drying
approaching_dry
too_cold
too_hot
insufficient_light
wet
normal
```

The exact order may be refined through tests, but it must remain deterministic.

## Status entity

Existing entity:

```text
sensor.<plant>_status
```

Allowed compact attributes:

```text
summary
reason
since
```

Example:

```yaml
state: drying
attributes:
  summary: Soil moisture is falling normally after watering
  reason: normal_drying
  since: "2026-09-22T10:30:00+02:00"
```

## Health entity

Existing entity:

```text
sensor.<plant>_health
```

Recommended states:

```text
good
watch
stressed
unknown
```

Examples:

```yaml
state: good
attributes:
  summary: Soil drying rate matches the current room conditions
```

```yaml
state: watch
attributes:
  summary: Soil has remained wetter than expected for several days
```

Health must not mirror every temporary condition.

## Needs-attention entity

Existing entity:

```text
binary_sensor.<plant>_needs_attention
```

Turn on only for sustained actionable conditions:

```text
needs_water
persistently_wet
prolonged_temperature_stress
several_days_insufficient_light
sensor_problem
```

Keep off for:

```text
recently_watered
wet
drying
one overcast day
brief cool period
short humidity excursion
```

## Summary rules

Visible summaries must be direct and natural.

Good examples:

```text
Soil moisture is falling normally after watering
```

```text
Soil is drying slowly because the room is cool and humid
```

```text
Light exposure has remained low for three days
```

```text
Natural and supplemental light provided adequate exposure today
```

Avoid:

```text
Environmental coefficient below threshold
```

```text
Window score insufficient
```

```text
Sensor condition requires attention
```

---

# 10. Phase 6: Learned baseline profiling

## Objective

Learn the behavior of the individual pot and placement after the deterministic temporal engine is stable.

Learn:

- Typical watering rise
- Typical peak moisture
- Normal drying slope
- Typical time back to preferred range
- Normal daytime light exposure
- Normal supplemental-light pattern
- Normal temperature range
- Normal humidity range
- Seasonal variation

## Learning safeguards

- Require minimum sample coverage.
- Keep indoor and outdoor baselines separate.
- Do not learn during invalid sensor periods.
- Do not learn temporary abnormal states as normal.
- Bound learned values using the selected care profile.
- Preserve inactive placement baselines.
- Keep all learned internals private.

## Baseline comparison

Example:

```text
Normal cycle:
48% → 35% over four days

Current cycle:
47% → 46% over four days
```

This provides stronger evidence of abnormal slow drying than a generic threshold alone.

---

# 11. Phase 7: Time-fast-forward testing

## Timeline tests

Use controlled Home Assistant time advancement to test complete behavior.

Required scenarios:

1. Normal watering and drying
2. High moisture immediately after watering
3. Moisture falling normally
4. Persistently wet soil
5. Repeated watering before sufficient drying
6. Approaching dry and needs water
7. Prolonged dryness
8. One cloudy day
9. Three consecutive low-light days
10. Strong outdoor radiation but shaded indoor placement
11. Sustained nighttime grow light
12. Five-minute nighttime room light
13. Grow-light session crossing midnight
14. Short cold excursion
15. Prolonged cold and wet condition
16. Warm, dry accelerated drying
17. Sensor unavailable during active cycle
18. Restart during a watering cycle
19. Forecast failure with valid cache
20. Forecast failure using Astral fallback
21. Complete daylight uncertainty
22. Air Quality failure with unaffected daylight
23. Two plants with the same name and independent histories
24. Zero moisture value
25. Categorical and numeric battery sources remain unaffected

## Regression requirements

Every phase must also prove:

- Existing measurements still update immediately.
- Existing entity IDs remain stable.
- Plant CRUD still works dynamically.
- Provider behavior remains untouched.
- No reload is added to plant sensor events.
- No raw temporal state is exposed as attribute clutter.
- Storage remains recoverable after restart.

---

# 12. Storage strategy

Do not overload the main plant configuration record.

Use separate internal storage sections:

```text
plant configuration
learned baselines
active temporal state
daily summaries
```

## Temporal moisture state

```python
@dataclass(frozen=True, slots=True)
class TemporalMoistureState:
    last_watering_event: datetime | None
    current_cycle_peak_moisture: float | None
    drying_rate_per_hour: float | None
    environmental_drying_factor: float | None
    adjusted_wet_duration_limit: float | None
    state_since: datetime | None
```

## Environmental drying context

```python
@dataclass(frozen=True, slots=True)
class EnvironmentalDryingContext:
    k_drying: float
    local_moisture_slope: float | None
    outdoor_radiation_bounded: float | None
    adjusted_wet_duration_limit: float
    confidence: str
```

## Storage-write policy

- Batch and delay writes.
- One sensor event must not force one disk write.
- Persist compact summaries rather than unlimited raw readings.
- Make interrupted writes recoverable.
- Validate restored timestamps before resuming duration calculations.

---

# 13. Entity output policy

Public entities remain compact and meaningful.

## Physical measurement entities

These remain current measurements:

```text
sensor.<plant>_moisture
sensor.<plant>_temperature
sensor.<plant>_humidity
sensor.<plant>_light
```

## Status entity

Describes the most useful current condition:

```text
normal
recently_watered
wet
drying
approaching_dry
needs_water
staying_wet
too_wet
too_dry
too_cold
too_hot
insufficient_light
sensor_problem
```

## Health entity

Represents longer-term assessment:

```text
good
watch
stressed
unknown
```

## Needs-attention binary sensor

Turns on only when sustained evidence supports a concrete action.

## Attribute limits

Do not expose:

- Raw observation arrays
- Internal thresholds
- Drying coefficients
- Weight matrices
- Confidence calculations
- Ring-buffer contents
- Daily summary internals
- Learning windows
- Debug state

Expose only concise fields such as:

```text
summary
reason
since
```

---

# 14. Delivery strategy

Implement this as controlled patch releases rather than one large rewrite.

## Release 1

```text
History foundation
Moisture cycle
Persistent wetness gating
```

This fixes the confirmed live problem where one `47%` reading immediately becomes `too_wet`.

## Release 2

```text
Temperature duration
Humidity duration
Combined cold/wet and warm/dry interpretation
```

## Release 3

```text
Daylight bounds
Natural and supplemental light accumulation
Forecast and Astral fallback
```

## Release 4

```text
Combined summaries
Learned plant baseline
Long-duration regression coverage
```

Each release must preserve its complete ZIP and exact restore file.

---

# 15. Final intended behavior

For a plant currently reporting:

```text
Moisture: 47%
Temperature: 21.3 °C
Humidity: 67%
Light: 50 lx
```

The initial interpretation should be:

```text
Status: wet
Health: good
Needs attention: off
```

If moisture begins falling:

```text
Status: drying
Health: good
Needs attention: off
```

If moisture remains elevated longer than expected after adjustment for cool temperature, high humidity, low light, and bounded outdoor conditions:

```text
Status: staying_wet
Health: watch
Needs attention: off
```

Only after persistent evidence:

```text
Status: too_wet
Health: watch
Needs attention: on
Reason: persistently_wet
```

This creates the correct separation between:

```text
measurement
current condition
developing trend
long-term health
actionable concern
```

### 1. Seasonal Dormancy Detection (Wintering)

Given that we are crossing the autumn equinox and approaching the darker months, your `effective_light_exposure` and Open-Meteo context will soon show a massive drop in natural light duration and intensity. Indoor plants respond by entering dormancy, meaning their water uptake plummets.

**The Mechanic:**
If the 30-day rolling average of `effective_light_exposure` drops below a profile-specific threshold, and baseline room temperatures drop slightly, the engine internally transitions the plant to a `dormant` state.

* **Impact on $k_{drying}$:** The dynamic wet-duration allowance is extended drastically (e.g., up to 300%).
* **Status Update:** The `needs_water` threshold is lowered so you aren't prompted to water a dormant plant at its usual summer frequency, preventing winter root rot.
* **Attribute:** `reason: seasonal_dormancy` is added to the status entity.

### 2. True VPD (Vapor Pressure Deficit) Integration

Phase 3 currently combines temperature and humidity into a contextual `normalized_vapor_dryness`. You can replace this abstraction with a scientifically accurate Vapor Pressure Deficit (VPD) calculation in kilopascals (kPa). VPD is the exact physical force pulling water out of the plant's leaves.

**The Mechanic:**
Calculate internal saturation vapor pressure (SVP) and actual vapor pressure (AVP) using the Tetens equation:


$$SVP = 0.61078 \times \exp\left(\frac{17.27 \times T}{T + 237.3}\right)$$

$$AVP = SVP \times \left(\frac{RH}{100}\right)$$

$$VPD = SVP - AVP$$

* **Impact:** Instead of guessing if "warm and humid" is stressful, VPD gives you an exact metric. If VPD is too high ($> 1.5$ kPa), the plant is transpiring too fast (`accelerated_drying`). If VPD is too low ($< 0.4$ kPa), the plant cannot breathe (`slow_drying_humid_condition`).
* **Output:** This replaces the basic temperature/humidity duration trackers with a single, highly accurate internal stress metric.

### 3. Partial Watering Detection (Volume Deficit)

Phase 2 detects a sharp moisture rise and flags it as `recently_watered`. Phase 6 learns the "Typical peak moisture". You can combine these to evaluate the *quality* of the watering event.

**The Mechanic:**
When a watering event settles and the moisture peaks, compare the new peak to the baseline learned peak.

* If the pot usually peaks at 65% but only hit 40% before plateauing, the soil was only partially saturated.
* **Status Impact:** Instead of returning to `normal`, the state shifts to `partial_watering` or immediately back to `approaching_dry`, preventing the engine from assuming the plant has a full reservoir to draw from over the next week.
