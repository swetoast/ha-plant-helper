# Plant Helper Learning Lifecycle

This map is the reference for Phase H completion and the pending live Home Assistant test.

## Status legend

- **Wired, behaviorally tested:** production path exists and pure behavior is exercised.
- **Wired, contract tested:** Home Assistant boundary exists and is checked structurally.
- **Pending live verification:** sandbox tests cannot substitute for a real Home Assistant lifecycle.

## Twelve-stage map

1. **Plant creation** | Owner: PlantStorage and Options flow | Wired, contract tested. Stores configuration and starts without a fabricated baseline.
2. **Calibration initialization** | Owner: LearnedStore and Runtime | Wired, behaviorally tested. Missing placement baseline means calibrating.
3. **Validated sample collection** | Owner: Coordinator and SampleStore | Wired, behaviorally and contract tested. Source timestamps, staleness, validation, dedupe, and gap semantics are covered.
4. **Daily reduction** | Owner: Runtime | Wired, behaviorally tested. Raw samples become compact daily records.
5. **Incomplete-calibration extension** | Owner: Runtime and LearnedStore | Wired, behaviorally tested. Day 14 remains extending when required evidence is missing.
6. **Baseline lock** | Owner: Calibration math and LearnedStore | Wired, behaviorally tested. Complete qualified evidence locks the placement baseline.
7. **Normal model execution** | Owner: Coordinator and Engine | Wired, behaviorally tested at the pure engine boundary; pending live entity verification.
8. **Watering-event detection** | Owner: Moisture model | Wired, behaviorally tested. Sustained steps are distinguished from reverting spikes.
9. **Post-lock adaptation** | Owner: Runtime and calibration math | Wired, behaviorally tested. Qualified higher peaks adapt M_max daily; M_dry is regenerated from the persisted threshold policy. Other constants stay locked.
10. **Placement transition** | Owner: PlantStorage, LearnedStore, Options flow, SampleStore | Wired, behaviorally and contract tested. The learned transition decides reuse versus calibration, preserves both baselines, and the options flow clears cross-placement samples and timers. Pending live options-flow verification.
11. **Manual recalibration** | Owner: Service layer, LearnedStore, SampleStore | Wired, contract tested. The selected plant's learned state and local samples are cleared; pending live service verification.
12. **Restart and persistence recovery** | Owner: LearnedStore, SampleStore, config-entry lifecycle | Wired, behaviorally and contract tested for persistence and unload; pending live restart verification.

## Current adaptation policy

- M_max adapts upward only from a new well-covered daily peak through the bounded EWMA.
- M_dry is recomputed from the baseline's persisted standard or custom dryness multiplier.
- Legacy baselines without policy metadata preserve their existing M_dry/M_max ratio as a migration fallback.
- Drying rate, DLI target, window transmission, thermal mean, and thermal swing remain locked until dedicated bounded multi-day policies are designed and tested.

## Required live Home Assistant checks

1. Edit an indoor plant to outdoor with no outdoor baseline and verify Calibration reports calibrating.
2. Return to a placement with a complete baseline and verify it becomes active without losing either baseline.
3. Confirm placement changes clear local sample continuity and dry, wet, cold, and warm timers.
4. Cross a local-day boundary after lock with a qualified new peak and verify M_max and M_dry persist after reload.
5. Restart during calibration and after baseline lock, then verify progress, baselines, timers, and entities recover.
6. Run recalibrate and verify only the target plant restarts calibration while species context remains available.
