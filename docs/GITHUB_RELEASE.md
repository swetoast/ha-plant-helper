# GitHub and HACS publication

## Repository

The configured repository is:

`https://github.com/swetoast/ha-plant-helper`

The integration manifest uses:

- Documentation: `https://github.com/swetoast/ha-plant-helper`
- Issue tracker: `https://github.com/swetoast/ha-plant-helper/issues`
- Code owner: `@swetoast`

## Repository structure

The repository contains one integration under `custom_components/plant_helper`, a root `README.md`, root `hacs.json`, user documentation under `docs`, tests, brand assets, and GitHub validation workflows.

## Publish

1. Push this repository tree to `https://github.com/swetoast/ha-plant-helper` with `main` as the default branch.
2. Confirm the HACS and Hassfest workflows pass.
3. Create the Git tag matching the version in `manifest.json`.
4. Create a full GitHub release from the tag.
5. In HACS, add `https://github.com/swetoast/ha-plant-helper` as a custom repository with category **Integration**.
6. Install Plant Helper, restart Home Assistant, and complete the smoke test in the maintenance plan.

## Default HACS submission

Public listing in the default HACS catalog is a separate process. First verify that custom-repository installation works and that the HACS and Hassfest workflows pass. Then follow the current HACS inclusion process.
