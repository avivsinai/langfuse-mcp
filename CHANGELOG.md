# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.6.5] - 2026-04-02
### Changed
- Switched releases to the shared PR-based `scripts/release.sh` flow, with `CHANGELOG.md` supplying the GitHub release notes and CI creating the version tag only after the merged release commit verifies.

### Fixed
- Pinned release verification and build to Python 3.12 so release automation no longer drifts onto unsupported Python 3.14 toolchains.
- Ignored `dist/.gitignore` during local release artifact verification so release prep now checks the same wheel and source tarball set that CI publishes.
- Removed deprecated release shims so there is exactly one supported release entrypoint.


## [0.6.4] - 2026-04-01

### Fixed
- Cleared `dist/` before release builds and restricted GitHub release uploads to the wheel and source tarball, so automation no longer attaches a stray `.gitignore` asset to Langfuse MCP releases.
- Added the same release metadata guard to the PyPI and Docker publish workflows that the GitHub release and skill publish flows already use, so a mistagged tag cannot publish inconsistent artifacts.
- Verified release metadata in the PyPI and Docker publish workflows before building artifacts from a version tag.

## [0.6.3] - 2026-04-01

### Changed
- Switched PyPI and Docker publishing to run directly from version-tag pushes so the full release chain executes even when the GitHub release itself is created by automation.

## [0.6.2] - 2026-04-01

### Added
- A GitHub release workflow that turns version tags into published GitHub releases with built Python distributions attached, keeping GitHub, PyPI, Docker, and skill publishing on the same release event.

### Fixed
- Verified skill and plugin metadata before skill publishing so a mismatched tag cannot partially publish registry artifacts.
- Treated `Version already exists` as success when a skill publish reruns after retrying without an alias, preventing false-negative publish failures on release reruns.

## [0.6.1] - 2026-04-01

### Fixed
- Resolved pyright errors and Ruff line-length violations in the new annotation queue and scores tooling.
- Verified skill and plugin metadata before skill publishing so mismatched release tags fail fast.

## [0.6.0] - 2026-03-31

### Added
- Annotation queue tools for listing, creating, assigning, updating, and deleting queue items.
- Scores v2 tools for inspecting modern Langfuse scoring data.

### Changed
- Notified the skills marketplace from default-branch pushes after merges.

### Fixed
- Staged the optional Codex plugin manifest during skill releases.
- Skipped invalid skill aliases during skill publication instead of failing the whole release.

## [0.5.4] - 2026-03-30

### Changed
- Switched skill publishing to a tag-based release flow so versioned skill publishes align with Git tags.

## [0.5.3] - 2026-03-29

### Added
- Codex plugin manifests with richer interface metadata for marketplace consumers.

### Changed
- Polished the OSS release surface with better templates, security metadata, troubleshooting docs, and synchronized skill trees.

### Fixed
- Aligned plugin manifest versions with release tags.

## [0.5.2] - 2026-02-08

### Fixed
- Resolved `DateTime` parse errors in `get_session_details` and audited related session handling paths.

## [0.5.1] - 2026-01-27

### Changed
- Improved the datasets playbook, skill installation docs, and `check-skills` CI coverage.

### Fixed
- Corrected Claude MCP installation syntax for environment variables and clarified dataset item upsert behavior.

## [0.5.0] - 2026-01-23

### Added
- Dataset management tools plus a `--read-only` mode for safer production access.

### Changed
- Added versioned skill publishing metadata and automated skild-based skill publishing.

## [0.4.2] - 2026-01-19

### Changed
- Expanded installation guidance and the "Other Clients" documentation.

## [0.4.1] - 2026-01-19

### Changed
- Simplified the README and refreshed CLI usage examples to match the current command surface.

## [0.4.0] - 2026-01-19

### Added
- A Claude Code skill for Langfuse MCP.

### Changed
- Added gitleaks secret scanning and pre-commit hooks.

## [0.3.4] - 2026-01-13

### Changed
- Added prominent warning in README Quick Start for Python 3.14 users with workaround (`uvx --python 3.11`)

### Fixed
- Aligned CI Python matrix with supported versions (3.10–3.13).
- Restored an early Python 3.14 runtime guard and made Langfuse `timeout` param optional based on SDK support.
- Made integration test teardown tolerant of connection-closed cleanup without hiding real errors.

## [0.3.3] - 2026-01-13

### Fixed
- **Python 3.14 incompatibility**: Blocked Python 3.14 in `requires-python` constraint. The Langfuse SDK uses Pydantic v1 internally which [doesn't support Python 3.14](https://github.com/langfuse/langfuse/issues/9618). Will re-enable once Langfuse migrates to Pydantic v2.

## [0.3.2] - 2026-01-13

### Fixed
- **Timeout configuration**: The Langfuse SDK defaults to an aggressive 5-second timeout which caused `ReadTimeout` errors when Langfuse cloud experiences latency. The MCP server now defaults to **30 seconds** and supports `--timeout` CLI flag and `LANGFUSE_TIMEOUT` environment variable for customization.

## [0.3.0] - 2026-01-06

### Added
- **Prompt management tools** - get, list, create, and update Langfuse prompts:
  - `get_prompt`, `get_prompt_unresolved`, `list_prompts`
  - `create_text_prompt`, `create_chat_prompt`, `update_prompt_labels`
- **Selective tool loading** via `--tools` flag or `LANGFUSE_MCP_TOOLS` env var
  - Load only needed tool groups (traces, observations, sessions, exceptions, prompts, schema)
  - Reduces token overhead when full toolset not required
- Unit tests covering new prompt tools

### Changed
- Bumped Langfuse SDK minimum version to `3.11.2` (still capped below 4.0.0).

## [0.2.1] - 2025-10-20

### Fixed
- Added guardrails to prevent running on Python 3.14+, documenting that the current Langfuse SDK dependency only supports Python 3.10–3.13 and updating packaging metadata so `uvx langfuse-mcp` resolves a compatible interpreter automatically.

## [0.2.0] - 2025-01-06

### Changed
- **BREAKING**: Migrated to Langfuse SDK v3.x (requires `langfuse>=3.0.0`)
- **BREAKING**: Tool responses now use envelope format `{"data": ..., "metadata": {...}}`
- Updated test doubles and unit tests to model the v3 API surface and ensure compatibility going forward
- MCP CLI now reads Langfuse credentials (`public_key`, `secret_key`, `host`) from a `.env` file or environment variables by default, keeping CLI flags optional
- Normalized output mode handling, tool envelopes, and logging configuration; added CLI options for log level/console output and standardized responses across all tools
- Docker image installs the local repository (`pip install .`) so containers run the same code under development instead of the last PyPI release, and now bundles `git` so dynamic versioning works during image builds
- README now documents how to execute the working tree with `uv run --from /path/to/langfuse-mcp`, clarifies why Docker builds should come from the local checkout, and shows how to install the repository version with `uv pip install --editable .`

### Added
- Docker support with Dockerfile for containerized deployments
- Environment variable support for credentials via `.env` files
- Enhanced logging configuration with `--log-level` and `--log-to-console` flags
- Pagination metadata in API responses

### Removed
- Dropped Langfuse v2 SDK support (now requires v3)

## [0.1.8] - 2025-01-05

### Added
- Comprehensive test suite with 10 tests covering all functionality
- Enhanced CI workflow with improved logging and verbose output
- Complete documentation with proper docstrings for all test files

### Changed
- Improved GitHub Actions workflow for better visibility and debugging
- Enhanced repository structure with complete test coverage

### Fixed
- All linting and formatting issues resolved
- Proper dependency management and build process

## [0.1.7] - 2025-01-05

### Changed
- Pinned Langfuse dependency to stable v2 branch (`>=2.60,<3.0.0`) for compatibility
- Enhanced CI matrix to test both Langfuse v2 and v3 (v3 allowed to fail)
- Removed uv.lock from version control as recommended for libraries

### Added
- Optional dev-v3 dependency group for future Langfuse v3 migration testing

## [0.1.6] - 2025-04-01

## [0.1.5] - 2025-03-31

### Added
- Enhanced README with detailed output processing information
- Added publish guidelines in project documentation

### Changed
- Improved data processing and output handling
- Increased get_error_count max age limit from 100 minutes to 7 days
- Updated documentation to include README reference in Cursor rules

## [0.1.4] - 2025-03-25

### Added
- Enhanced response processing with truncation for large fields
- Added more robust date parsing
- Improved exception handling

### Changed
- Refactored MCP runner and updated logging 
- Removed Optional type hints from function signatures for better compatibility
- Updated project metadata and build configuration

## [0.1.2] - 2025-03-20

### Added
- Added dynamic versioning with uv-dynamic-versioning
- Version history documentation
- Recommended GitHub Actions for CI/CD

### Changed
- Removed mcp.json from git history and added to gitignore
- Improved test configuration

## [0.1.1] - 2025-03-15

### Added
- Initial release with basic MCP server functionality
- Tool for retrieving traces based on filters
- Tool for finding exceptions grouped by file, function, or type
- Tool for getting detailed exception information
- Tool for retrieving sessions
- Tool for getting error counts
- Tool for fetching data schema

### Changed

### Deprecated

### Removed

### Fixed

### Security

## [0.1.0] - 2025-XX-XX
- Initial release 
