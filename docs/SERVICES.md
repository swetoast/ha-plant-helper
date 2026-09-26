# Actions and services

## plant_helper.relearn

Forget what a plant has learned for its current placement and start
calibrating again. Use it after repotting, moving the probe, or when the learned
moisture range is plainly wrong.

Target: one or more Plant Helper plant devices.

```yaml
action: plant_helper.relearn
target:
  device_id: <plant device id>
```

What it resets, for the current placement only: the learned moisture range, the
per-watering values (rise, peak, drying speed, time back to range), the light,
temperature and humidity norms, and the monthly record. The baseline for the
other placement (indoor or outdoor) is kept. Recent readings and daily summaries
stay, because the statuses need them, but learning only counts days from the
relearn day on. Until it has recalibrated, the plant is judged by its care
profile. The calibration sensor shows the progress.

Errors: calling it without a target, or with a device that is not a loaded
Plant Helper plant, fails with a message and changes nothing.

## Managing plants

Plants are added, edited, re-matched and removed from Settings > Devices &
services > Plant Helper > Configure:

- Add a plant
- Edit a plant
- Re-match species data
- Remove a plant

The care profile and, for outdoor plants, the rain limit can also be changed
from their entities on the plant's device; that saves the plant the same way
Edit a plant does. Change shared settings with Reconfigure on the integration
entry.
