# Test foundation

The test suite describes the current component rather than historical implementation phases.

## Rules

- Every production Python module is assigned to a current behavioral foundation area.
- Every public top-level function and class is listed in `test_foundation_inventory.py`.
- Adding or removing production modules or public definitions requires updating the inventory and adding behavioral tests.
- New tests use normal pytest test functions. A small number of retained legacy modules still execute assertions during collection; they may be converted when those areas are changed, but new collection-time test scripts must not be added.
- Home Assistant public contracts, entity states, attributes, persistence, provider behavior, calculation models, and failure paths are tested independently.
- Configuration and options schemas must be exercised far enough to detect unsupported Home Assistant selector arguments before release.
- Release validation runs against the extracted ZIP, not only the working tree.

## Foundation areas

- Integration lifecycle, services, config flow, and options
- Coordinator collection and runtime orchestration
- Sensor and binary-sensor public contracts
- Engine calculations, thresholds, precedence, and validation
- Learned state, samples, and configuration persistence
- Perenual, Trefle, and iNaturalist integrations
- Species enrichment and cache behavior
- Forecast, Open-Meteo, STRANG, and radiation handling
- Manifest, translations, documentation, and release packaging

## Release validation

Before publishing a release:

1. Run the complete test suite.
2. Build the release ZIP without Python or pytest cache files.
3. Extract the ZIP into a clean directory.
4. Run compilation and the complete test suite against the extracted files.
5. Confirm the manifest and README identify the intended version.
6. Confirm the recovery script recreates the exact release ZIP.
7. Review public documentation and issue templates against the current configuration and runtime behavior.
