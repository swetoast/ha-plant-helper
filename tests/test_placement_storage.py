import pytest
from domain.placement import decide_placement_transition
from domain.storage_revision import check_plant_revision,next_revisions,StorageConflictError

def test_placement_transition_preserves_baselines():
    result=decide_placement_transition("indoor","outdoor",destination_baseline_complete=False)
    assert result.changed and result.clear_active_samples and result.preserve_indoor_baseline and result.preserve_outdoor_baseline and result.destination_requires_calibration

def test_no_transition():
    result=decide_placement_transition("indoor","indoor",destination_baseline_complete=False)
    assert not result.changed and not result.clear_active_samples and not result.destination_requires_calibration

def test_revisions():
    check_plant_revision(2,2)
    with pytest.raises(StorageConflictError): check_plant_revision(3,2)
    assert next_revisions(4,7)==(5,8)
