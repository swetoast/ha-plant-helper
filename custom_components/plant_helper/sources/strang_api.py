"""STRÅNG open-data API source — fetch radiation directly from SMHI.

An alternative to reading a third-party STRÅNG custom integration's sensors: this
calls SMHI's keyless STRÅNG point endpoint and builds the SAME `MacroReading` the
HA-sensor path produces, so nothing downstream changes. It returns the full
hourly series for the last ~48h in one call per parameter, which is exactly the
shape the DLI / light-hours accumulators want (true complete calendar days on the
correct, lagged time axis).

STRÅNG covers the Nordic region only (grid over Scandinavia), so callers gate on
`in_nordic_coverage(lat, lon)` first and fall back to an external sensor outside
it — and additionally treat an empty/all-None response as "not covered", since
the grid edges are fuzzy (interpolation from the 4 nearest points).

Parsing and assembly are pure and unit-tested; the async fetch is a thin wrapper
(lazy aiohttp import so the pure functions test without it).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from ..engine.util import to_float, parse_iso
from .smhi import EXPECTED_LAG_HOURS, MacroReading

STRANG_BASE = (
    "https://opendata-download-metanalys.smhi.se/api/category/strang1g/version/1"
)

# Logical name -> STRÅNG parameter id (PAR is W/m^2 since 2017-03-29, matching
# the engine's PAR_WH_TO_DLI conversion).
PARAMETERS = {
    "global": 117,
    "par": 120,
    "diffuse": 122,
    "direct_horizontal": 121,
    "direct_normal": 118,
}

# Global horizontal irradiance (W/m^2) -> illuminance (lux). ~120 lux per W/m^2
# is a standard daylight luminous-efficacy approximation. Only the indoor light
# model consumes outdoor_lux, and it does so as a ratio (indoor/outdoor), so the
# exact factor largely cancels.
GLOBAL_W_TO_LUX = 120.0

# STRÅNG model grid covers the Nordic countries. Generous land bounding box; the
# runtime empty-response check is the real gate for fuzzy edges. Iceland
# (negative longitude) is intentionally outside.
_LAT_MIN, _LAT_MAX = 54.0, 72.0
_LON_MIN, _LON_MAX = 4.0, 32.0


def in_nordic_coverage(lat: float | None, lon: float | None) -> bool:
    """Cheap pre-check: is this coordinate inside the STRÅNG grid's land extent?"""
    if lat is None or lon is None:
        return False
    return _LAT_MIN <= lat <= _LAT_MAX and _LON_MIN <= lon <= _LON_MAX


def use_strang_api(source: str, lat: float | None, lon: float | None) -> bool:
    """Decide whether to use the STRÅNG API given the configured source.

    'api' -> always; 'sensors' -> never; 'auto' -> only inside Nordic coverage.
    """
    if source == "api":
        return True
    if source == "sensors":
        return False
    return in_nordic_coverage(lat, lon)


def _parse_dt(value: Any) -> datetime | None:
    """Parse a STRÅNG timestamp (UTC). Point responses use 'YYYY-MM-DD HH:MM:SS'
    (space, no zone); be tolerant of the RFC3339 't'/'Z' forms too."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return parse_iso(text)


def parse_strang_series(payload: Any) -> list[tuple[datetime, float]]:
    """Parse a STRÅNG point response into sorted (utc_datetime, value) pairs.

    Skips entries with a missing/unparseable timestamp or non-numeric value.
    """
    out: list[tuple[datetime, float]] = []
    if not isinstance(payload, list):
        return out
    for item in payload:
        if not isinstance(item, Mapping):
            continue
        ts = _parse_dt(item.get("date_time"))
        val = to_float(item.get("value"))
        if ts is not None and val is not None:
            out.append((ts, val))
    out.sort(key=lambda p: p[0])
    return out


def latest_point(series: Sequence[tuple[datetime, float]]) -> tuple[datetime, float] | None:
    return series[-1] if series else None


def has_usable_data(series_by_param: Mapping[str, Sequence[tuple[datetime, float]]]) -> bool:
    """True if PAR or global came back with any non-zero point — the runtime
    coverage gate for fuzzy grid edges (all-zero/empty => treat as not covered)."""
    for name in ("par", "global"):
        for _, v in series_by_param.get(name) or ():
            if v:  # any non-zero value
                return True
    return False


def macro_from_series(
    series_by_param: Mapping[str, Sequence[tuple[datetime, float]]],
    now: datetime,
    *,
    api_issue: bool = False,
    expected_lag_hours: float = EXPECTED_LAG_HOURS,
) -> MacroReading:
    """Build a MacroReading from fetched series — identical shape to the sensor
    path's `parse_macro`. Staleness uses the age of the newest PAR point."""
    def latest_val(param: str) -> float | None:
        pt = latest_point(series_by_param.get(param) or [])
        return pt[1] if pt else None

    par_point = latest_point(series_by_param.get("par") or [])
    par = par_point[1] if par_point else None
    selected_dt = par_point[0] if par_point else None
    age = (now - selected_dt).total_seconds() / 3600.0 if selected_dt else None

    glob = latest_val("global")
    lux = glob * GLOBAL_W_TO_LUX if glob is not None else None

    genuinely_stale = (
        api_issue
        or par is None
        or (age is not None and age > expected_lag_hours)
    )
    return MacroReading(
        par=par,
        global_irradiance=glob,
        diffuse_irradiance=latest_val("diffuse"),
        direct_horizontal=latest_val("direct_horizontal"),
        direct_normal=latest_val("direct_normal"),
        outdoor_lux=lux,
        data_stale=(age is not None and age > 2.0),  # informational: routine lag
        api_issue=api_issue,
        age_hours=age,
        selected_data_time=selected_dt,
        stale=genuinely_stale,
    )


# --- async fetch (thin; lazy aiohttp import) ------------------------------

async def fetch_series(
    session: Any,
    lat: float,
    lon: float,
    parameter: int,
    *,
    from_: str | None = None,
    to: str | None = None,
    timeout_s: float = 15.0,
) -> list[tuple[datetime, float]]:
    """Fetch and parse one parameter's point series. Returns [] on any failure."""
    import aiohttp

    url = f"{STRANG_BASE}/geotype/point/lon/{lon}/lat/{lat}/parameter/{parameter}/data.json"
    params: dict[str, str] = {}
    if from_:
        params["from"] = from_
    if to:
        params["to"] = to
    try:
        timeout = aiohttp.ClientTimeout(total=timeout_s)
        async with session.get(url, params=params, timeout=timeout) as resp:
            if resp.status != 200:
                return []
            payload = await resp.json(content_type=None)
        return parse_strang_series(payload)
    except Exception:  # noqa: BLE001 - network best-effort; caller falls back
        return []


async def fetch_macro(
    session: Any,
    lat: float,
    lon: float,
    now: datetime,
    *,
    lookback_hours: int = 48,
    expected_lag_hours: float = EXPECTED_LAG_HOURS,
) -> tuple[MacroReading, dict[str, list[tuple[datetime, float]]]]:
    """Fetch all modelled parameters and assemble a MacroReading.

    Also returns the raw per-parameter series so the coordinator can buffer the
    full PAR day (complete-day DLI) rather than one point per cycle.
    """
    from_ = (now - timedelta(hours=lookback_hours)).strftime("%Y%m%d%H")
    series_by_param: dict[str, list[tuple[datetime, float]]] = {}
    for name, param in PARAMETERS.items():
        series_by_param[name] = await fetch_series(session, lat, lon, param, from_=from_)
    macro = macro_from_series(
        series_by_param, now, expected_lag_hours=expected_lag_hours
    )
    return macro, series_by_param
