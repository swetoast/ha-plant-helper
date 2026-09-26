"""Which Home Assistant repair issues Plant Helper should show. Pure.

Every issue is informational (not fixable from the Repairs dialog); each
description says where to fix it. The runtime creates the issues returned here
and deletes any other Plant Helper issue, so a problem that is gone clears
itself.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping

PROVIDER_TITLES = {"trefle": "Trefle", "perenual": "Perenual"}


def desired_issues(
    plants: Mapping[str, Mapping[str, Any]],
    *,
    sensor_exists: Callable[[str], bool] | None,
    provider_problems: Mapping[str, str],
    perenual_free: bool,
) -> dict[str, tuple[str, dict[str, str]]]:
    """{issue_id: (translation_key, placeholders)}.

    ``sensor_exists`` is None until Home Assistant has finished starting, when
    other integrations' sensors may still be loading.
    """
    issues: dict[str, tuple[str, dict[str, str]]] = {}
    not_rematched: list[str] = []
    for plant_uuid, config in sorted(plants.items()):
        name = str(config.get("display_name", plant_uuid))
        entity_id = config.get("soil_moisture")
        if sensor_exists is not None and entity_id and not sensor_exists(str(entity_id)):
            issues[f"missing_moisture_sensor_{plant_uuid}"] = (
                "missing_moisture_sensor",
                {"plant": name, "entity_id": str(entity_id)},
            )
        if config.get("species") and not config.get("species_sources"):
            not_rematched.append(name)
    if not_rematched:
        issues["plants_not_rematched"] = (
            "plants_not_rematched",
            {"plants": ", ".join(not_rematched)},
        )
    for provider, kind in sorted(provider_problems.items()):
        if kind == "auth":
            issues[f"provider_key_rejected_{provider}"] = (
                "provider_key_rejected",
                {"provider": PROVIDER_TITLES.get(provider, provider)},
            )
        elif kind == "plan" and provider == "perenual" and not perenual_free:
            # On the free plan a paywalled record is expected; with the plan set
            # to paid it means the key is not on a paid plan.
            issues["perenual_plan_mismatch"] = ("perenual_plan_mismatch", {})
    return issues
