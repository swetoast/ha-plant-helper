"""SMHI STRÅNG macro source (design.md section 2 & 6).

Reads the STRÅNG grid sensors (PAR, global/diffuse/direct irradiance, derived
outdoor lux) and decides usability.

IMPORTANT (confirmed from a live dump): STRÅNG publishes with an inherent lag —
often most of a day. `data_stale: true` with `latest_available_age_hours` around
17-24h is the *normal* operating state, not an error. So `data_stale` alone must
NOT trigger the baseline failover, or it would fire constantly and defeat DLI.

Usability model:
  * Genuinely stale (-> failover to learned baseline) only when the API-issue
    binary sensor is on, the newest data is older than the expected-lag
    threshold, or PAR is missing.
  * Otherwise the data is usable but lagged: PAR samples are timestamped by
    their `selected_data_time` (the UTC hour the value represents), so the DLI
    integral is built on the correct — if delayed — time axis. Outdoor DLI is
    therefore "most-recent-complete-day", which is fine for a slowly-changing
    plant.

Entity ids and attribute names below are confirmed against the live dump.
Parsing is pure and tested; `read_macro` is the thin HA wrapper.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from ..engine.accumulator import Sample
from ..engine.util import to_float, parse_iso

DEFAULT_ENTITIES = {
    "par": "sensor.smhi_strang_par",
    "global": "sensor.smhi_strang_global_irradiance",
    "diffuse": "sensor.smhi_strang_diffuse_irradiance",
    "direct_horizontal": "sensor.smhi_strang_direct_horizontal_irradiance",
    "direct_normal": "sensor.smhi_strang_direct_normal_irradiance",
    "outdoor_lux": "sensor.smhi_strang_outdoor_lux",
}
API_ISSUE_ENTITY = "binary_sensor.smhi_strang_api_issue"

_AGE_KEYS = ("latest_available_age_hours", "age_hours", "data_age_hours")
_STALE_KEYS = ("data_stale", "stale", "is_stale")
_SELECTED_TIME_KEYS = ("selected_data_time", "latest_available_data_time")

# Newest STRÅNG data older than this is genuinely stale (STRÅNG stopped
# publishing), as opposed to the routine ~1-day lag.
EXPECTED_LAG_HOURS = 36.0


@dataclass(frozen=True, slots=True)
class MacroReading:
    par: float | None
    global_irradiance: float | None
    diffuse_irradiance: float | None
    direct_horizontal: float | None
    direct_normal: float | None
    outdoor_lux: float | None
    data_stale: bool          # raw STRÅNG flag (routinely true due to lag)
    api_issue: bool           # binary_sensor.smhi_strang_api_issue
    age_hours: float | None
    selected_data_time: datetime | None
    stale: bool               # failover decision: don't trust for DLI


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "on", "stale"}
    return False


def parse_macro(
    values: Mapping[str, float | None],
    attributes: Mapping[str, Mapping[str, Any]] | None = None,
    *,
    api_issue: bool = False,
    expected_lag_hours: float = EXPECTED_LAG_HOURS,
) -> MacroReading:
    """Build a MacroReading and decide genuine staleness.

    `values` maps logical names to floats; `attributes` maps the same names to
    their HA attribute dicts. Genuine staleness (failover) = API issue, or newest
    data older than `expected_lag_hours`, or PAR missing — NOT the raw
    `data_stale` flag on its own.
    """
    attributes = attributes or {}
    par = to_float(values.get("par"))

    raw_stale = False
    max_age: float | None = None
    selected_dt: datetime | None = None
    for attrs in attributes.values():
        if not isinstance(attrs, Mapping):
            continue
        for k in _STALE_KEYS:
            if k in attrs and _truthy(attrs[k]):
                raw_stale = True
        for k in _AGE_KEYS:
            age = to_float(attrs.get(k))
            if age is not None:
                max_age = age if max_age is None else max(max_age, age)
        for k in _SELECTED_TIME_KEYS:
            dt = parse_iso(attrs.get(k))
            if dt is not None and selected_dt is None:
                selected_dt = dt

    genuinely_stale = (
        api_issue
        or par is None
        or (max_age is not None and max_age > expected_lag_hours)
    )

    return MacroReading(
        par=par,
        global_irradiance=to_float(values.get("global")),
        diffuse_irradiance=to_float(values.get("diffuse")),
        direct_horizontal=to_float(values.get("direct_horizontal")),
        direct_normal=to_float(values.get("direct_normal")),
        outdoor_lux=to_float(values.get("outdoor_lux")),
        data_stale=raw_stale,
        api_issue=api_issue,
        age_hours=max_age,
        selected_data_time=selected_dt,
        stale=genuinely_stale,
    )


def macro_par_sample(reading: MacroReading, fallback_ts: datetime) -> Sample:
    """A PAR sample for the accumulator, on the correct (lagged) time axis.

    Timestamped by `selected_data_time` when available so the DLI integral uses
    the hour the value actually represents. A genuinely-stale reading yields an
    invalid sample (a hole, never a zero) per the design.md section 6 failover.
    """
    ts = reading.selected_data_time or fallback_ts
    if reading.stale or reading.par is None:
        return Sample(ts, reading.par, valid=False)
    return Sample(ts, reading.par, valid=True)


def effective_today_dli(
    measured_dli: float | None,
    coverage: float,
    baseline_dli: float | None,
    *,
    min_coverage: float = 0.5,
) -> float | None:
    """Choose measured DLI or the learned baseline for the period.

    Low PAR coverage (genuine staleness left holes) -> learned baseline instead
    of a spuriously-low measured value.
    """
    if measured_dli is not None and coverage >= min_coverage:
        return measured_dli
    return baseline_dli if baseline_dli is not None else measured_dli


async def read_macro(
    hass: Any,
    entities: Mapping[str, str] | None = None,
    *,
    api_issue_entity: str = API_ISSUE_ENTITY,
    expected_lag_hours: float = EXPECTED_LAG_HOURS,
) -> MacroReading:
    """Read STRÅNG sensors + the API-issue binary sensor from HA (thin wrapper)."""
    ent = dict(DEFAULT_ENTITIES)
    if entities:
        ent.update(entities)

    values: dict[str, float | None] = {}
    attributes: dict[str, dict[str, Any]] = {}
    for logical, entity_id in ent.items():
        state = hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable", None):
            values[logical] = None
            attributes[logical] = {}
            continue
        values[logical] = to_float(state.state)
        attributes[logical] = dict(getattr(state, "attributes", {}) or {})

    api_issue = False
    issue_state = hass.states.get(api_issue_entity)
    if issue_state is not None:
        api_issue = str(issue_state.state).lower() == "on"

    return parse_macro(
        values, attributes, api_issue=api_issue, expected_lag_hours=expected_lag_hours
    )
