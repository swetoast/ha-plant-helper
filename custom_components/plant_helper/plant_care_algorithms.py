"""Plant care algorithms for Plant Helper.

This module provides higher quality derived plant metrics using linked
room/plant sensors together with plant-specific thresholds from the local
plant database/API providers.
"""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

MAX_RUNTIME_SAMPLES = 432  # ~3 days at 10 minute cadence
SAMPLE_MIN_INTERVAL = timedelta(minutes=10)


class PlantCareAlgorithms:
    """Algorithms for plant care monitoring and predictions."""

    def __init__(self, hass: HomeAssistant, storage: Any | None = None) -> None:
        """Initialize algorithms helper."""
        self.hass = hass
        self._storage = storage
        self._samples: dict[str, deque[dict[str, Any]]] = defaultdict(
            lambda: deque(maxlen=MAX_RUNTIME_SAMPLES)
        )
        self._last_sample_at: dict[str, datetime] = {}

    async def record_runtime_sample(
        self,
        plant_id: str,
        plant_data: dict[str, Any],
    ) -> None:
        """Record one runtime sample from linked entities.

        Samples are throttled to avoid excessive processing while still enabling
        daily light accumulation and stress-duration calculations.
        """
        now = dt_util.now()
        last_sample_at = self._last_sample_at.get(plant_id)
        if last_sample_at and (now - last_sample_at) < SAMPLE_MIN_INTERVAL:
            return

        sample = {
            "ts": now,
            "temperature": self._linked_state_float(plant_data, "temperature"),
            "lux": self._linked_state_float(plant_data, "lux"),
            "air_humidity": self._linked_state_float(plant_data, "air_humidity"),
            "soil_moisture": self._linked_state_float(plant_data, "moisture"),
        }
        self._samples[plant_id].append(sample)
        self._last_sample_at[plant_id] = now

    def clear_plant(self, plant_id: str) -> None:
        """Clear runtime data for a plant that was removed."""
        self._samples.pop(plant_id, None)
        self._last_sample_at.pop(plant_id, None)

    def compute_metrics(
        self,
        plant_id: str,
        plant_data: dict[str, Any],
        plant_info: dict[str, Any],
    ) -> dict[str, Any]:
        """Compute the full derived metric bundle for a configured plant."""
        now = dt_util.now()
        current = self._current_environment(plant_data)
        samples = self._recent_samples(plant_id, current, now)
        thresholds = self._build_thresholds(plant_info)

        light_stats = self._calculate_light_stats(samples, plant_info, thresholds)
        growth_mode = self._growth_mode(now, light_stats["light_score"])
        temperature_stats = self._calculate_temperature_stress(
            samples,
            thresholds["temperature_min"],
            thresholds["temperature_max"],
        )
        moisture_stats = self._calculate_soil_moisture(
            now=now,
            plant_data=plant_data,
            plant_info=plant_info,
            thresholds=thresholds,
            current=current,
            growth_mode=growth_mode,
        )
        humidity_stats = self._calculate_air_humidity(current, thresholds)
        maintenance = self._calculate_maintenance(now, plant_data, growth_mode)

        moisture_score = self._score_moisture(
            moisture_stats["calculated_soil_moisture"],
            thresholds["soil_moisture_min"],
            thresholds["soil_moisture_max"],
        )
        light_score = light_stats["light_score"]
        temp_score = max(0.0, 100.0 - temperature_stats["temperature_stress_load"])
        humidity_score = humidity_stats["air_humidity_score"]
        maintenance_score = max(
            0.0,
            100.0
            - (maintenance["inspection_penalty"] + maintenance["fertilizer_penalty"]),
        )

        health_score = round(
            (moisture_score * 0.35)
            + (light_score * 0.25)
            + (temp_score * 0.20)
            + (humidity_score * 0.10)
            + (maintenance_score * 0.10),
            1,
        )

        watering_state = self._watering_state(
            moisture_stats["calculated_soil_moisture"],
            thresholds["soil_moisture_min"],
            thresholds["soil_moisture_max"],
        )
        light_state = self._light_state(light_score)
        temperature_state = self._temperature_state(
            current["temperature"],
            thresholds["temperature_min"],
            thresholds["temperature_max"],
        )
        air_humidity_state = self._air_humidity_state(
            current["air_humidity"],
            thresholds["air_humidity_min"],
            thresholds["air_humidity_max"],
        )
        health_state = self._health_state(health_score)
        primary_issue = self._primary_issue(
            watering_state,
            light_state,
            temperature_state,
            air_humidity_state,
            maintenance,
            temperature_stats,
        )
        care_action = self._care_action(
            watering_state,
            light_state,
            temperature_state,
            air_humidity_state,
            maintenance,
            primary_issue,
        )

        return {
            **current,
            **thresholds,
            **light_stats,
            **temperature_stats,
            **moisture_stats,
            **humidity_stats,
            **maintenance,
            "growth_mode": growth_mode,
            "watering_state": watering_state,
            "light_state": light_state,
            "temperature_state": temperature_state,
            "air_humidity_state": air_humidity_state,
            "health_score": health_score,
            "health_state": health_state,
            "primary_issue": primary_issue,
            "care_action": care_action,
            "moisture_score": round(moisture_score, 1),
            "temperature_score": round(temp_score, 1),
            "maintenance_score": round(maintenance_score, 1),
            "updated_at": now.isoformat(),
        }

    def _recent_samples(
        self,
        plant_id: str,
        current: dict[str, float | None],
        now: datetime,
    ) -> list[dict[str, Any]]:
        """Return recent runtime samples with a live fallback sample."""
        samples = list(self._samples.get(plant_id, []))
        if not samples or samples[-1].get("ts") != now:
            samples.append({"ts": now, **current})

        cutoff = now - timedelta(hours=24)
        return [sample for sample in samples if sample["ts"] >= cutoff]

    def _current_environment(
        self,
        plant_data: dict[str, Any],
    ) -> dict[str, float | None]:
        return {
            "temperature": self._linked_state_float(plant_data, "temperature"),
            "lux": self._linked_state_float(plant_data, "lux"),
            "air_humidity": self._linked_state_float(plant_data, "air_humidity"),
            "soil_moisture_sensor": self._linked_state_float(plant_data, "moisture"),
        }

    def _build_thresholds(self, plant_info: dict[str, Any]) -> dict[str, float]:
        thresholds = (
            plant_info.get("thresholds", {}) if isinstance(plant_info, dict) else {}
        )

        def _num(*keys: str, default: float) -> float:
            for key in keys:
                value = thresholds.get(key)
                if value is not None:
                    try:
                        return float(value)
                    except (TypeError, ValueError):
                        continue
            return float(default)

        return {
            "soil_moisture_min": _num("soil_moisture_min", default=30),
            "soil_moisture_max": _num("soil_moisture_max", default=65),
            "temperature_min": _num("temperature_min", default=16),
            "temperature_max": _num("temperature_max", default=29),
            "air_humidity_min": _num("air_humidity_min", default=35),
            "air_humidity_max": _num("air_humidity_max", default=70),
            "lux_min": _num("lux_min", default=1200),
        }

    def _calculate_light_stats(
        self,
        samples: list[dict[str, Any]],
        plant_info: dict[str, Any],
        thresholds: dict[str, float],
    ) -> dict[str, Any]:
        lux_min = thresholds["lux_min"]
        target_minutes = self._target_light_minutes(plant_info)

        sufficient = 0.0
        bright = 0.0
        low = 0.0
        excessive = 0.0
        peak_lux = 0.0

        for previous, current in zip(samples, samples[1:]):
            minutes = max(1.0, (current["ts"] - previous["ts"]).total_seconds() / 60)
            lux = previous.get("lux")
            if lux is None:
                continue

            peak_lux = max(peak_lux, float(lux))

            if lux >= lux_min:
                sufficient += minutes
            else:
                low += minutes

            if lux >= max(lux_min * 1.75, 12000):
                bright += minutes
            if lux >= max(lux_min * 3.0, 25000):
                excessive += minutes

        current_lux = float(samples[-1].get("lux") or 0.0) if samples else 0.0
        peak_lux = max(peak_lux, current_lux)

        base_score = min(100.0, (sufficient / max(target_minutes, 1.0)) * 100.0)
        excessive_penalty = min(20.0, excessive / 30.0)
        light_score = round(max(0.0, min(100.0, base_score - excessive_penalty)), 1)

        return {
            "daily_light_target_minutes": round(target_minutes, 1),
            "sufficient_light_minutes_today": round(sufficient, 1),
            "bright_light_minutes_today": round(bright, 1),
            "low_light_minutes_today": round(low, 1),
            "peak_lux_today": round(peak_lux, 1),
            "light_score": light_score,
            "current_lux": round(current_lux, 1),
        }

    def _target_light_minutes(self, plant_info: dict[str, Any]) -> float:
        sunlight = plant_info.get("sunlight")
        values: list[str] = []

        if isinstance(sunlight, str):
            values = [sunlight.lower()]
        elif isinstance(sunlight, list):
            values = [str(item).lower() for item in sunlight if item]

        if any("full sun" in value for value in values):
            return 480.0
        if any("part shade" in value or "partial shade" in value for value in values):
            return 300.0
        if any("shade" in value for value in values):
            return 180.0
        if any("bright indirect" in value or "filtered" in value for value in values):
            return 360.0
        return 300.0

    def _calculate_temperature_stress(
        self,
        samples: list[dict[str, Any]],
        temp_min: float,
        temp_max: float,
    ) -> dict[str, Any]:
        cold_minutes = 0.0
        heat_minutes = 0.0
        max_temp = None
        min_temp = None

        for previous, current in zip(samples, samples[1:]):
            minutes = max(1.0, (current["ts"] - previous["ts"]).total_seconds() / 60)
            temp = previous.get("temperature")
            if temp is None:
                continue

            max_temp = temp if max_temp is None else max(max_temp, temp)
            min_temp = temp if min_temp is None else min(min_temp, temp)

            if temp < temp_min:
                cold_minutes += minutes
            elif temp > temp_max:
                heat_minutes += minutes

        total_stress = cold_minutes + heat_minutes
        stress_load = min(100.0, total_stress / 14.4)

        return {
            "cold_stress_minutes_today": round(cold_minutes, 1),
            "heat_stress_minutes_today": round(heat_minutes, 1),
            "temperature_stress_load": round(stress_load, 1),
            "min_temp_today": round(min_temp, 1) if min_temp is not None else None,
            "max_temp_today": round(max_temp, 1) if max_temp is not None else None,
        }

    def _calculate_soil_moisture(
        self,
        *,
        now: datetime,
        plant_data: dict[str, Any],
        plant_info: dict[str, Any],
        thresholds: dict[str, float],
        current: dict[str, float | None],
        growth_mode: str,
    ) -> dict[str, Any]:
        soil_min = thresholds["soil_moisture_min"]
        soil_max = thresholds["soil_moisture_max"]
        watering_profile = str(plant_info.get("watering") or "average").lower()

        base_dry_per_hour = {
            "minimum": 0.22,
            "low": 0.22,
            "average": 0.38,
            "medium": 0.38,
            "frequent": 0.55,
            "high": 0.55,
        }.get(watering_profile, 0.38)

        temperature = current.get("temperature")
        air_humidity = current.get("air_humidity")
        current_lux = current.get("lux")

        temp_factor = (
            1.0
            if temperature is None
            else 1.0 + max(-0.25, min(0.7, (temperature - 22.0) * 0.035))
        )
        humidity_factor = (
            1.0
            if air_humidity is None
            else 1.0 + max(-0.25, min(0.5, (45.0 - air_humidity) * 0.012))
        )
        light_factor = (
            1.0
            if current_lux is None
            else 1.0
            + max(-0.15, min(0.55, (current_lux - thresholds["lux_min"]) / 25000.0))
        )
        growth_factor = {
            "dormant": 0.70,
            "slow_growth": 0.85,
            "active_growth": 1.00,
            "peak_growth": 1.10,
        }.get(growth_mode, 1.0)

        drying_rate = max(
            0.08,
            base_dry_per_hour
            * temp_factor
            * humidity_factor
            * light_factor
            * growth_factor,
        )

        watered_at = (
            self._parse_datetime(plant_data.get("last_watered"))
            or self._parse_datetime(plant_data.get("added_date"))
            or now
        )
        elapsed_hours = max(0.0, (now - watered_at).total_seconds() / 3600.0)

        post_watering_level = min(98.0, max(soil_max + 18.0, 82.0))
        model_moisture = max(
            0.0,
            min(100.0, post_watering_level - (elapsed_hours * drying_rate)),
        )

        real_moisture = current.get("soil_moisture_sensor")
        if real_moisture is not None:
            calculated = (real_moisture * 0.7) + (model_moisture * 0.3)
            source = "blended"
        else:
            calculated = model_moisture
            source = "modeled"

        hours_until = (
            0.0
            if calculated <= soil_min
            else max(0.0, (calculated - soil_min) / max(drying_rate, 0.08))
        )
        watering_urgency = min(
            100.0,
            max(
                0.0,
                ((soil_min + 12.0 - calculated) * 4.2)
                + max(0.0, (24.0 - hours_until)) * 0.8,
            ),
        )

        return {
            "calculated_soil_moisture": round(calculated, 1),
            "soil_moisture_model": round(model_moisture, 1),
            "soil_moisture_source": source,
            "drying_rate_factor": round(drying_rate / max(base_dry_per_hour, 0.01), 2),
            "drying_rate_per_hour": round(drying_rate, 3),
            "days_since_watered": round(elapsed_hours / 24.0, 2),
            "days_until_watering": round(hours_until / 24.0, 2),
            "watering_urgency": round(watering_urgency, 1),
        }

    def _calculate_air_humidity(
        self,
        current: dict[str, float | None],
        thresholds: dict[str, float],
    ) -> dict[str, Any]:
        rh = current.get("air_humidity")
        rh_min = thresholds["air_humidity_min"]
        rh_max = thresholds["air_humidity_max"]

        if rh is None:
            return {
                "air_humidity_score": 50.0,
                "humidity_deficit": None,
            }

        if rh < rh_min:
            deficit = rh_min - rh
            score = max(0.0, 100.0 - (deficit * 4.0))
        elif rh > rh_max:
            deficit = rh - rh_max
            score = max(0.0, 100.0 - (deficit * 2.5))
        else:
            deficit = 0.0
            score = 100.0

        return {
            "air_humidity_score": round(score, 1),
            "humidity_deficit": round(deficit, 1),
        }

    def _calculate_maintenance(
        self,
        now: datetime,
        plant_data: dict[str, Any],
        growth_mode: str,
    ) -> dict[str, Any]:
        inspected_days = self._days_since(now, plant_data.get("last_inspected"))
        fertilized_days = self._days_since(now, plant_data.get("last_fertilized"))

        inspection_due_days = 14 if growth_mode in {"active_growth", "peak_growth"} else 21
        fertilizer_due_days = 30 if growth_mode in {"active_growth", "peak_growth"} else 60

        inspection_penalty = (
            0.0
            if inspected_days is None
            else max(0.0, (inspected_days - inspection_due_days) * 2.0)
        )
        fertilizer_penalty = (
            0.0
            if fertilized_days is None
            else max(0.0, (fertilized_days - fertilizer_due_days) * 1.5)
        )

        if inspected_days is None and fertilized_days is None:
            maintenance_state = "up_to_date"
        elif (
            inspected_days is not None
            and inspected_days > inspection_due_days + 7
            and fertilized_days is not None
            and fertilized_days > fertilizer_due_days + 10
        ):
            maintenance_state = "overdue"
        elif inspected_days is not None and inspected_days > inspection_due_days:
            maintenance_state = "inspection_due"
        elif fertilized_days is not None and fertilized_days > fertilizer_due_days:
            maintenance_state = "fertilizer_due"
        elif (
            inspected_days is not None and inspected_days > inspection_due_days - 2
        ) or (
            fertilized_days is not None and fertilized_days > fertilizer_due_days - 5
        ):
            maintenance_state = "due_soon"
        else:
            maintenance_state = "up_to_date"

        return {
            "days_since_inspected": inspected_days,
            "days_since_fertilized": fertilized_days,
            "inspection_due_days": inspection_due_days,
            "fertilizer_due_days": fertilizer_due_days,
            "inspection_penalty": round(min(35.0, inspection_penalty), 1),
            "fertilizer_penalty": round(min(25.0, fertilizer_penalty), 1),
            "maintenance_state": maintenance_state,
        }

    def _score_moisture(self, moisture: float, soil_min: float, soil_max: float) -> float:
        if soil_min <= moisture <= soil_max:
            return 100.0
        if moisture < soil_min:
            deficit = soil_min - moisture
            return max(0.0, 100.0 - (deficit * 4.5))
        excess = moisture - soil_max
        return max(0.0, 100.0 - (excess * 2.5))

    def _watering_state(self, moisture: float, soil_min: float, soil_max: float) -> str:
        if moisture >= soil_max + 10:
            return "saturated"
        if moisture >= soil_max:
            return "moist"
        if moisture >= soil_min:
            return "ideal"
        if moisture >= soil_min - 8:
            return "slightly_dry"
        if moisture >= soil_min - 18:
            return "dry"
        return "critically_dry"

    def _light_state(self, light_score: float) -> str:
        if light_score < 20:
            return "dark"
        if light_score < 40:
            return "low"
        if light_score < 70:
            return "adequate"
        if light_score < 90:
            return "bright"
        return "excessive"

    def _temperature_state(
        self,
        temp: float | None,
        temp_min: float,
        temp_max: float,
    ) -> str:
        if temp is None:
            return "unknown"
        if temp < temp_min - 3:
            return "cold"
        if temp < temp_min:
            return "cool"
        if temp <= temp_max:
            return "ideal"
        if temp <= temp_max + 3:
            return "warm"
        return "hot"

    def _air_humidity_state(
        self,
        rh: float | None,
        rh_min: float,
        rh_max: float,
    ) -> str:
        if rh is None:
            return "unknown"
        if rh < rh_min - 15:
            return "very_dry"
        if rh < rh_min:
            return "dry"
        if rh <= rh_max:
            return "comfortable"
        if rh <= rh_max + 10:
            return "humid"
        return "very_humid"

    def _growth_mode(self, now: datetime, light_score: float) -> str:
        month = now.month
        if month in {11, 12, 1, 2}:
            return "dormant" if light_score < 55 else "slow_growth"
        if month in {3, 4, 9, 10}:
            return "active_growth" if light_score >= 60 else "slow_growth"
        return "peak_growth" if light_score >= 75 else "active_growth"

    def _health_state(self, health_score: float) -> str:
        if health_score >= 90:
            return "excellent"
        if health_score >= 75:
            return "good"
        if health_score >= 55:
            return "fair"
        if health_score >= 30:
            return "poor"
        return "critical"

    def _primary_issue(
        self,
        watering_state: str,
        light_state: str,
        temperature_state: str,
        air_humidity_state: str,
        maintenance: dict[str, Any],
        temperature_stats: dict[str, Any],
    ) -> str:
        if watering_state in {"dry", "critically_dry"}:
            return "underwatered"
        if watering_state == "saturated":
            return "overwatered"
        if light_state in {"dark", "low"}:
            return "low_light"
        if temperature_state == "hot" or temperature_stats.get("heat_stress_minutes_today", 0) > 180:
            return "heat_stress"
        if temperature_state == "cold" or temperature_stats.get("cold_stress_minutes_today", 0) > 180:
            return "cold_stress"
        if air_humidity_state in {"very_dry", "dry"}:
            return "dry_air"
        if maintenance.get("maintenance_state") in {"inspection_due", "fertilizer_due", "overdue"}:
            return "maintenance_overdue"
        return "none"

    def _care_action(
        self,
        watering_state: str,
        light_state: str,
        temperature_state: str,
        air_humidity_state: str,
        maintenance: dict[str, Any],
        primary_issue: str,
    ) -> str:
        if watering_state in {"dry", "critically_dry"}:
            return "water_now"
        if watering_state == "slightly_dry":
            return "water_soon"
        if light_state in {"dark", "low"}:
            return "increase_light"
        if temperature_state == "hot":
            return "cool_location"
        if temperature_state == "cold":
            return "warm_location"
        if air_humidity_state in {"very_dry", "dry"}:
            return "raise_humidity"
        if maintenance.get("maintenance_state") == "inspection_due":
            return "inspect_plant"
        if maintenance.get("maintenance_state") == "fertilizer_due":
            return "fertilize"
        if maintenance.get("maintenance_state") == "overdue":
            return "inspect_plant"
        return "none" if primary_issue == "none" else "monitor"

    def _linked_state_float(
        self,
        plant_data: dict[str, Any],
        key: str,
    ) -> float | None:
        entity_id = self._get_linked_entity(plant_data, key)
        if not entity_id:
            return None

        state = self.hass.states.get(entity_id)
        if state is None or state.state in {"unknown", "unavailable", "none", None}:
            return None

        try:
            return float(state.state)
        except (TypeError, ValueError):
            return None

    def _get_linked_entity(self, plant_data: dict[str, Any], key: str) -> str | None:
        entities = plant_data.get("entities", {}) if isinstance(plant_data, dict) else {}
        aliases = {
            "moisture": ("moisture", "moisture_entity", "humidity", "humidity_entity", "soil_moisture", "soil_humidity"),
            "temperature": ("temperature", "temperature_entity", "temp", "temp_entity", "room_temperature", "soil_temperature"),
            "lux": ("lux", "lux_entity", "light", "light_entity", "room_lux"),
            "air_humidity": ("air_humidity", "air_humidity_entity", "room_humidity"),
        }.get(key, (key, f"{key}_entity"))

        for alias in aliases:
            value = entities.get(alias)
            if value:
                return str(value)
        return None

    def _parse_datetime(self, value: Any) -> datetime | None:
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        try:
            parsed = dt_util.parse_datetime(str(value))
            return dt_util.as_local(parsed) if parsed is not None else None
        except (TypeError, ValueError):
            return None

    def _days_since(self, now: datetime, value: Any) -> int | None:
        parsed = self._parse_datetime(value)
        if parsed is None:
            return None
        return max(0, int((now - parsed).total_seconds() // 86400))
