"""Pure serialize and restore for the temporal store.

The Home Assistant ``Store`` object is owned by the runtime; this module only
transforms between the in-memory history/state objects and a JSON-safe payload,
and validates restored timestamps. Restore never trusts a stored clock blindly:
observations with a missing, naive, unparseable, or future timestamp are
dropped, and state timestamps that fail the same check become ``None`` so
duration timing resumes cleanly instead of resting on a bad value.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from .history import ObservationHistory
from .moisture import TemporalMoistureState
from .observation import PlantObservation

STORE_VERSION = 1

# Tolerance for small clock skew when rejecting future timestamps.
_FUTURE_SKEW = timedelta(minutes=5)


def serialize_store(
    histories: dict[str, ObservationHistory],
    states: dict[str, TemporalMoistureState],
) -> dict:
    """Build a JSON-safe payload from the live histories and states."""
    plants: dict[str, dict] = {}
    for uuid in set(histories) | set(states):
        history = histories.get(uuid)
        rolling = (
            [_observation_to_dict(o) for o in history.observations]
            if history is not None
            else []
        )
        state = states.get(uuid)
        plants[uuid] = {
            "rolling": rolling,
            "moisture_state": _state_to_dict(state) if state is not None else None,
        }
    return {"version": STORE_VERSION, "plants": plants}


def restore_store(
    data: object, now: datetime
) -> tuple[dict[str, ObservationHistory], dict[str, TemporalMoistureState]]:
    """Rebuild histories and states from a stored payload, validating clocks."""
    histories: dict[str, ObservationHistory] = {}
    states: dict[str, TemporalMoistureState] = {}
    if not isinstance(data, dict) or data.get("version") != STORE_VERSION:
        return histories, states
    plants = data.get("plants")
    if not isinstance(plants, dict):
        return histories, states
    for uuid, blob in plants.items():
        if not isinstance(blob, dict):
            continue
        observations = []
        for raw in blob.get("rolling") or []:
            obs = _observation_from_dict(raw, now)
            if obs is not None:
                observations.append(obs)
        observations.sort(key=lambda o: o.observed_at)
        history = ObservationHistory()
        for obs in observations:
            history.append(obs)
        histories[uuid] = history
        state = _state_from_dict(blob.get("moisture_state"), now)
        if state is not None:
            states[uuid] = state
    return histories, states


def _observation_to_dict(obs: PlantObservation) -> dict:
    return {
        "observed_at": obs.observed_at.isoformat(),
        "moisture": obs.moisture,
        "soil_temperature": obs.soil_temperature,
        "moisture_valid": obs.moisture_valid,
        "soil_temperature_valid": obs.soil_temperature_valid,
        "light": obs.light,
        "humidity": obs.humidity,
        "light_valid": obs.light_valid,
        "humidity_valid": obs.humidity_valid,
    }


def _observation_from_dict(raw: object, now: datetime) -> PlantObservation | None:
    if not isinstance(raw, dict):
        return None
    observed_at = _parse_time(raw.get("observed_at"), now)
    if observed_at is None:
        return None
    return PlantObservation(
        observed_at=observed_at,
        moisture=_as_float(raw.get("moisture")),
        soil_temperature=_as_float(raw.get("soil_temperature")),
        moisture_valid=bool(raw.get("moisture_valid")),
        soil_temperature_valid=bool(raw.get("soil_temperature_valid")),
        light=_as_float(raw.get("light")),
        humidity=_as_float(raw.get("humidity")),
        light_valid=bool(raw.get("light_valid")),
        humidity_valid=bool(raw.get("humidity_valid")),
    )


def _state_to_dict(state: TemporalMoistureState) -> dict:
    return {
        "status": state.status,
        "state_since": _iso(state.state_since),
        "last_watering_event": _iso(state.last_watering_event),
        "cycle_peak_moisture": state.cycle_peak_moisture,
        "drying_rate_per_hour": state.drying_rate_per_hour,
        "adjusted_wet_duration_limit": state.adjusted_wet_duration_limit,
        "confidence": state.confidence,
    }


def _state_from_dict(raw: object, now: datetime) -> TemporalMoistureState | None:
    if not isinstance(raw, dict):
        return None
    status = raw.get("status")
    if not isinstance(status, str):
        return None
    confidence = raw.get("confidence")
    if confidence not in ("low", "medium", "high"):
        confidence = "low"
    return TemporalMoistureState(
        status=status,
        state_since=_parse_time(raw.get("state_since"), now),
        last_watering_event=_parse_time(raw.get("last_watering_event"), now),
        cycle_peak_moisture=_as_float(raw.get("cycle_peak_moisture")),
        drying_rate_per_hour=_as_float(raw.get("drying_rate_per_hour")),
        adjusted_wet_duration_limit=_as_float(raw.get("adjusted_wet_duration_limit")),
        confidence=confidence,
    )


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


def _parse_time(value: object, now: datetime) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    if parsed > now + _FUTURE_SKEW:
        return None
    return parsed


def _as_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
