from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class PlacementTransition:
    changed: bool
    clear_active_samples: bool
    reset_placement_timers: bool
    preserve_indoor_baseline: bool
    preserve_outdoor_baseline: bool
    destination_requires_calibration: bool

def decide_placement_transition(current: str, destination: str, *, destination_baseline_complete: bool) -> PlacementTransition:
    if current not in {"indoor","outdoor"} or destination not in {"indoor","outdoor"}: raise ValueError("placement")
    changed=current!=destination
    return PlacementTransition(changed,changed,changed,True,True,changed and not destination_baseline_complete)
