from __future__ import annotations
from dataclasses import dataclass,field
from typing import Any
from .domain.runtime import RuntimeCollection

@dataclass(slots=True)
class PlantHelperRuntime:
    plants: RuntimeCollection=field(default_factory=RuntimeCollection)
    platform_callbacks: dict[str,Any]=field(default_factory=dict)
    entities: dict[str,dict[str,Any]]=field(default_factory=dict)
    storage: Any=None
    register_listeners: Any=None
    replace_listeners: Any=None
    evaluate: Any=None
    schedule_enrichment: Any=None
    schedule_reconciliation: Any=None
    handle_placement_change: Any=None
    handle_species_change: Any=None
    destination_baseline_complete: Any=None
    cancel_tasks: Any=None
    unsubscribe_listeners: Any=None
    block_evaluation: Any=None
    remove_entity_registry: Any=None
    verify_entities_gone: Any=None
    remove_device_registry: Any=None
    remove_owned_state: Any=None
    physical_processor: Any=None
    physical_subscriptions: Any=None
    cached_environment: Any=None
    learning: Any=None
    forecast_collector: Any=None
    air_quality_collector: Any=None
    environmental_snapshot: Any=None
    interpret_environment: Any=None
    species_enrichment: Any=None
    species_image_proxy: Any=None
