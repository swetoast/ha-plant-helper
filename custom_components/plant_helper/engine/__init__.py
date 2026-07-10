"""Plant Helper decision engine.

Pure-logic layer (no Home Assistant imports) that turns validated time-series
telemetry into learned baselines, model states, and an overall health score.
Kept HA-free so every model can be unit-tested in isolation.
"""
