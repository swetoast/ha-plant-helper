# GitHub and HACS publication

## Repository metadata required before publication

The packaged manifest uses explicit placeholders because the final GitHub owner and repository URL were not provided when the package was built. Replace all three values before publishing:

- `@OWNER` in `custom_components/plant_helper/manifest.json`
- `https://github.com/OWNER/plant-helper`
- `https://github.com/OWNER/plant-helper/issues`

Use the actual GitHub account or organization and repository name. Do not publish the placeholders.

## Repository structure

The repository contains one integration under `custom_components/plant_helper`, a root `README.md`, root `hacs.json`, user documentation under `docs`, tests, and GitHub validation workflows.

## Publish

1. Replace the manifest placeholders.
2. Push the repository to GitHub with `main` as the default branch.
3. Confirm the HACS and Hassfest workflows pass.
4. Create a Git tag matching the manifest version, currently `0.0.1`.
5. Create a full GitHub release from the tag.
6. In HACS, add the repository as a custom repository with category **Integration**.
7. Install, restart Home Assistant, and complete the smoke test in the maintenance plan.

## Default HACS submission

Public listing in the default HACS catalog is a separate process. First verify that custom-repository installation works and that the validation workflows pass. Then follow the current HACS inclusion process.
