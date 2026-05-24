# Contributing to Plant Helper

Thank you for your interest in contributing to Plant Helper! This document provides guidelines and instructions for contributing.

## Code of Conduct

Be respectful, inclusive, and constructive. We're all here to make plant care easier for Home Assistant users.

## Ways to Contribute

### Reporting Bugs

Found a bug? Help us fix it:

1. Check [existing issues](https://github.com/swetoast/ha-plant-helper/issues) first
2. Create a new issue using the bug report template
3. Include:
   - Home Assistant version
   - Plant Helper version
   - Steps to reproduce
   - Expected vs actual behavior
   - Relevant logs (Settings → System → Logs)

### Suggesting Features

Have an idea for improvement?

1. Check [existing feature requests](https://github.com/swetoast/ha-plant-helper/issues?q=is%3Aissue+label%3Aenhancement)
2. Create a new issue using the feature request template
3. Explain:
   - The use case
   - How it would work
   - Why it would be valuable

### Improving Documentation

Documentation improvements are always welcome:

- Fix typos or unclear explanations
- Add examples or screenshots
- Improve installation instructions
- Add troubleshooting tips

Submit a PR directly or create an issue.

### Contributing Code

#### Development Setup

1. **Fork and Clone**
   ```bash
   git clone https://github.com/swetoast/ha-plant-helper.git
   cd ha-plant-helper
   ```

2. **Set up Home Assistant Dev Environment**
   
   The easiest way to test is using a Home Assistant development container or a test instance.

3. **Link the Integration**
   ```bash
   # Symlink to your HA config directory
   ln -s $(pwd)/custom_components/plant_helper ~/.homeassistant/custom_components/plant_helper
   ```

4. **Create a Feature Branch**
   ```bash
   git checkout -b feature/my-awesome-feature
   ```

#### Development Guidelines

**Code Style**
- Follow [PEP 8](https://pep8.org/) Python style guide
- Use type hints for function parameters and return values
- Use descriptive variable and function names
- Keep functions focused and single-purpose

**Structure**
- Provider code goes in `api/` directory
- Sensors in `sensor.py` and `binary_sensor.py`
- Config flow in `config_flow.py`
- Storage operations in `storage.py`
- Shared utilities in appropriate modules

**Testing**
- Test your changes in a real Home Assistant instance
- Test with and without API keys configured
- Test with different plant searches
- Verify sensors update correctly
- Check config flow works end-to-end

**Logging**
- Use `_LOGGER.debug()` for detailed flow information
- Use `_LOGGER.info()` for significant events
- Use `_LOGGER.warning()` for recoverable issues
- Use `_LOGGER.error()` for problems that affect functionality
- Use `_LOGGER.exception()` for caught exceptions

#### Making Changes

1. **Write Clean Code**
   - Keep functions under 50 lines when possible
   - Add docstrings for public functions
   - Use meaningful variable names
   - Comment complex logic

2. **Update Strings**
   - If adding config flow steps, update `strings.json` and `translations/en.json`
   - Add helpful `data_description` for form fields
   - Keep descriptions concise and user-friendly

3. **Update Documentation**
   - Update README.md if adding features
   - Add to CHANGELOG.md under "Unreleased"
   - Update code comments for complex logic

4. **Test Thoroughly**
   - Manual testing in Home Assistant
   - Test different scenarios
   - Verify no errors in logs

#### Submitting Changes

1. **Commit Your Changes**
   ```bash
   git add .
   git commit -m "Add feature: brief description"
   ```

   Use clear commit messages:
   - `Add feature: description`
   - `Fix: description of bug fixed`
   - `Update: description of change`
   - `Docs: description of documentation change`

2. **Push to Your Fork**
   ```bash
   git push origin feature/my-awesome-feature
   ```

3. **Create a Pull Request**
   - Go to the original repository
   - Click "New Pull Request"
   - Select your branch
   - Fill out the PR template
   - Explain what changes you made and why

4. **Respond to Feedback**
   - Address review comments
   - Make requested changes
   - Push updates to the same branch

## Areas That Need Help

### High Priority

- [ ] Unit tests and test coverage
- [ ] Integration tests for API providers
- [ ] Better error messages for common issues
- [ ] Performance optimization for large plant collections

### Medium Priority

- [ ] Support for more plant data providers
- [ ] Advanced watering schedules
- [ ] Plant growth tracking over time
- [ ] Fertilization tracking and reminders

### Low Priority

- [ ] Custom plant images
- [ ] Plant care journal/notes
- [ ] Export/import plant database
- [ ] Integration with plant identification apps

## Adding New Data Providers

Want to add support for a new plant data API?

1. Create a new file in `api/` (e.g., `api/newprovider.py`)
2. Inherit from `PlantProviderBase` in `api/base.py`
3. Implement the required methods:
   - `async def fetch_plant(self, query: str) -> ProviderResult`
4. Add rate limiting using `@rate_limited_provider` decorator
5. Update `plant_data_api.py` to include your provider
6. Add configuration options in `config_flow.py`
7. Update `strings.json` and `translations/en.json`
8. Document in README.md

## Questions?

- Open a [Discussion](https://github.com/swetoast/ha-plant-helper/discussions)
- Create an [Issue](https://github.com/swetoast/ha-plant-helper/issues)

## Recognition

Contributors will be recognized in:
- CHANGELOG.md for their contributions
- README.md credits section (for significant contributions)

Thank you for helping make Plant Helper better! 🌱
