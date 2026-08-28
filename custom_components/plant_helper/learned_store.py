"""Versioned learned-constants store (review #12 & #13).

Persists the crown-jewel learned state — the constants that cost 14 real days to
earn — plus calibration progress, dormancy state, and per-plant config. Two
things the design review called for:

  * Dual indoor/outdoor baselines (#12): each plant keeps a separate baseline set
    per placement, so a plant that summers outside and winters inside swaps
    baselines instead of wiping and recalibrating on every move.
  * Versioned persistence + migration (#13): a schema version and a `migrate`
    hook, so a future schema bump upgrades old data rather than discarding it.

The schema manipulation is pure and unit-tested; `LearnedStore` is the thin Home
Assistant wrapper (Store + debounced save), mirroring the 3.3.0 runtime-sample
persistence pattern.
"""

from __future__ import annotations

from typing import Any

SCHEMA_VERSION = 4
STORE_KEY = "plant_helper.learned"
SAVE_DELAY = 30.0

PLACEMENTS = ("indoor", "outdoor")


def empty_data() -> dict[str, Any]:
    return {"version": SCHEMA_VERSION, "plants": {}}


def migrate(data: Any) -> dict[str, Any]:
    """Upgrade stored data to the current schema.

    Unknown/empty -> fresh. Older versions are structurally upgraded here; today
    the only pre-v4 shape is "no learned store yet", so we initialise cleanly.
    The hook exists so future bumps have a home.
    """
    if not isinstance(data, dict) or "plants" not in data:
        return empty_data()
    version = data.get("version", 0)
    if version == SCHEMA_VERSION:
        return data
    # Future: branch per version. For now, carry plants forward and stamp.
    data = dict(data)
    data["version"] = SCHEMA_VERSION
    data.setdefault("plants", {})
    return data


def _plant(data: dict[str, Any], plant_id: str) -> dict[str, Any]:
    return data.setdefault("plants", {}).setdefault(
        plant_id,
        {
            "config": {},
            "baselines": {},      # placement -> constants + status
            "calibration": {},    # placement -> {started_at, status, day_records}
            "dormancy": {"dormant": False, "days_in_state": 999, "changed_at": None},
        },
    )


def set_config(data: dict[str, Any], plant_id: str, config: dict[str, Any]) -> None:
    _plant(data, plant_id)["config"] = dict(config)


def get_config(data: dict[str, Any], plant_id: str) -> dict[str, Any]:
    return _plant(data, plant_id).get("config", {})


def get_placement(data: dict[str, Any], plant_id: str) -> str:
    return _plant(data, plant_id).get("config", {}).get("placement", "indoor")


# --- dual baselines -------------------------------------------------------

def set_baseline(
    data: dict[str, Any],
    plant_id: str,
    placement: str,
    constants: dict[str, Any],
    *,
    status: str,
    locked_at: str | None = None,
) -> None:
    """Store the learned constants for one placement, preserving the other."""
    record = _plant(data, plant_id)
    entry = dict(constants)
    entry["status"] = status
    entry["locked_at"] = locked_at
    record.setdefault("baselines", {})[placement] = entry


def active_baseline(
    data: dict[str, Any],
    plant_id: str,
    placement: str | None = None,
) -> dict[str, Any] | None:
    """Return the baseline for the given (or configured) placement, if any."""
    record = _plant(data, plant_id)
    placement = placement or record.get("config", {}).get("placement", "indoor")
    return record.get("baselines", {}).get(placement)


def has_baseline(data: dict[str, Any], plant_id: str, placement: str) -> bool:
    entry = _plant(data, plant_id).get("baselines", {}).get(placement)
    return bool(entry) and entry.get("status") == "complete"


def swap_placement(
    data: dict[str, Any],
    plant_id: str,
    new_placement: str,
) -> bool:
    """Change a plant's active placement without wiping the other baseline.

    Returns True if the target placement has no complete baseline yet (the
    caller should therefore (re)start calibration for it); False if a stored
    baseline is ready to use immediately.
    """
    if new_placement not in PLACEMENTS:
        raise ValueError(f"Unsupported placement: {new_placement}")
    record = _plant(data, plant_id)
    record.setdefault("config", {})["placement"] = new_placement
    needs_calibration = not has_baseline(data, plant_id, new_placement)
    if needs_calibration:
        progress = record.setdefault("calibration", {}).get(new_placement)
        if not isinstance(progress, dict) or progress.get("status") == "complete":
            record["calibration"][new_placement] = {
                "status": "calibrating",
                "day_records": [],
            }
        else:
            progress["status"] = (
                "extending" if progress.get("day_records") else "calibrating"
            )
    return needs_calibration


# --- calibration progress -------------------------------------------------

def set_calibration(
    data: dict[str, Any],
    plant_id: str,
    placement: str,
    progress: dict[str, Any],
) -> None:
    """Store opaque calibration progress (reduced daily scalars) for a placement."""
    _plant(data, plant_id).setdefault("calibration", {})[placement] = progress


def get_calibration(
    data: dict[str, Any],
    plant_id: str,
    placement: str,
) -> dict[str, Any] | None:
    return _plant(data, plant_id).get("calibration", {}).get(placement)


# --- dormancy -------------------------------------------------------------

def set_dormancy(
    data: dict[str, Any],
    plant_id: str,
    *,
    dormant: bool,
    days_in_state: int,
    changed_at: str | None,
) -> None:
    _plant(data, plant_id)["dormancy"] = {
        "dormant": dormant,
        "days_in_state": days_in_state,
        "changed_at": changed_at,
    }


def get_dormancy(data: dict[str, Any], plant_id: str) -> dict[str, Any]:
    return _plant(data, plant_id).get(
        "dormancy", {"dormant": False, "days_in_state": 999, "changed_at": None}
    )


def remove_plant(data: dict[str, Any], plant_id: str) -> None:
    data.get("plants", {}).pop(plant_id, None)


# --- Tier-2 daily-aggregate history (long-horizon trends) -----------------

DAILY_HISTORY_RETENTION_DAYS = 90


def append_daily(
    data: dict[str, Any],
    plant_id: str,
    summary: dict[str, Any],
    *,
    retention_days: int = DAILY_HISTORY_RETENTION_DAYS,
) -> None:
    """Append one day's aggregate summary, keeping the most recent N days.

    A summary carries at least {date, daily_dli, soil_temp_mean, par_mean}; used
    for 30-day dormancy slopes and weekly/3-day light means, so the Tier-1 raw
    buffer never needs weeks of high-resolution samples.
    """
    hist = _plant(data, plant_id).setdefault("daily_history", [])
    date = summary.get("date")
    # Replace same-date entry if re-run, else append.
    hist[:] = [h for h in hist if h.get("date") != date]
    hist.append(summary)
    hist.sort(key=lambda h: str(h.get("date")))
    if len(hist) > retention_days:
        del hist[: len(hist) - retention_days]


def get_daily(data: dict[str, Any], plant_id: str) -> list[dict[str, Any]]:
    return _plant(data, plant_id).get("daily_history", [])


def set_last_reduced(data: dict[str, Any], plant_id: str, date_iso: str) -> None:
    _plant(data, plant_id)["last_reduced_date"] = date_iso


def get_last_reduced(data: dict[str, Any], plant_id: str) -> str | None:
    return _plant(data, plant_id).get("last_reduced_date")


# --- persisted condition timers (reboot-safe "since" stamps) ---------------

def get_timer(data: dict[str, Any], plant_id: str, key: str) -> str | None:
    """ISO timestamp a condition became active, or None if inactive."""
    return _plant(data, plant_id).get("timers", {}).get(key)


def set_timer(data: dict[str, Any], plant_id: str, key: str, since_iso: str | None) -> None:
    """Stamp (or clear, with None) when a condition became active."""
    timers = _plant(data, plant_id).setdefault("timers", {})
    if since_iso is None:
        timers.pop(key, None)
    else:
        timers[key] = since_iso


class LearnedStore:
    """Thin Home Assistant wrapper around the pure schema functions."""

    def __init__(self, hass: Any) -> None:
        from homeassistant.helpers.storage import Store

        self._store = Store(hass, SCHEMA_VERSION, STORE_KEY)
        self._data: dict[str, Any] = empty_data()
        self._loaded = False

    async def async_load(self) -> dict[str, Any]:
        if self._loaded:
            return self._data
        self._loaded = True
        try:
            raw = await self._store.async_load()
        except Exception:  # noqa: BLE001
            import logging

            logging.getLogger(__name__).exception("Failed to load learned store")
            raw = None
        self._data = migrate(raw)
        return self._data

    @property
    def data(self) -> dict[str, Any]:
        return self._data

    def schedule_save(self) -> None:
        if not self._loaded:
            return
        self._store.async_delay_save(lambda: self._data, SAVE_DELAY)

    async def async_save(self) -> None:
        if not self._loaded:
            return
        try:
            await self._store.async_save(self._data)
        except Exception:  # noqa: BLE001
            import logging

            logging.getLogger(__name__).exception("Failed to save learned store")
