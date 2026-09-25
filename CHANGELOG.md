# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]
### Changed
- Trace, session and observation reads go through Observations API v2 (`GET /api/public/v2/observations`). Langfuse Cloud removes `GET /traces`, `/traces/{id}`, `/sessions` and the v1 `/observations` routes on 2026-11-16 ([deprecated API migration](https://langfuse.com/faq/all/deprecated-api-migration)). Covers `fetch_traces`, `fetch_trace`, `fetch_observations`, `fetch_observation`, `fetch_sessions`, `get_session_details`, `get_user_sessions` and the route-decision tools. v2 is used whenever the SDK exposes it with `filter` (v4, and v3 3.11.2+ via `observations_v_2`); a server that answers 404/405 (self-hosted Langfuse v3) falls back to the old routes, and any other error propagates.
- **Breaking output change:** Traces are rebuilt from their root observation: `name`, `tags` and `release` from the trace context; `input`, `output`, `metadata` and `latency` from the root; `html_path` from the project id. `fetch_trace` also sums `total_cost` over the trace's observations and reads `scores` from Scores API v3 when the SDK has it (4.8.1+). `fetch_traces` loses total cost, scores and observation ids; observations still come with `include_observations=True`.
- **Breaking output change:** `fetch_sessions` groups the window's root observations by session: `id`, `last_trace_at`, `user_id`, `environment`, `project_id`. `last_trace_at` replaces `created_at` because v4 has no session object.
- `page` keeps working on the cursor-only endpoint by walking the cursor, up to page 50 (`ERR_LANGFUSE_V2_PAGE_LIMIT` beyond). `fetch_observations` no longer rejects `page > 1` on SDK v4.
- **Breaking output change:** v2 rows get the snake_case keys the v1 SDK models produced, and `input`/`output` strings are parsed back to JSON where they are JSON. Metadata values over 200 characters are truncated (the v2 default), except route-decision keys.
- `list_scores_v2` and `get_score_v2` read Scores API v3 (`GET /api/public/v3/scores`) through `scores_v3.get_many_v3` (SDK 4.8.1+); Langfuse Cloud removes `GET /v2/scores` and `/v2/scores/{id}` on 2026-11-16. Rows keep the v2 shape: `trace_id`, `observation_id` and `session_id` are copied out of the v3 `subject` (which stays), string scores also carry `string_value`, and `value` is typed by `data_type` (booleans are `true`/`false`). `total` is null because v3 has none; `next_page` is set while the cursor has more. A server that answers 404/405 falls back to the v2 routes.
- Score filters map to v3: `score_ids` becomes `id`; `operator`/`value` become `value`, `value_min` or `value_max` with the single `data_type` v3 requires (strict `>`/`<` also drop the boundary row, `!=` is rejected); `trace_id` together with `session_id` is rejected up front. `user_id` and `trace_tags`, which v3 dropped, still use `GET /v2/scores` and fail with `ERR_LANGFUSE_SCORES_V2_ONLY_FILTER` once it is gone.

## [0.11.0] - 2026-09-10
### Changed
- Exception tools (`find_exceptions`, `find_exceptions_in_file`, `get_exception_details`, `get_error_count`) now detect errors by observation `level == "ERROR"` with a shared complete scan across all observation types (V2 cursor endpoint preferred, page fallback), deduplicated by `(trace_id, observation_id)`, capped at 50 requests × 100 — the cap raises an explicit error instead of returning partial data.
- `find_exceptions` gains `group_by="name"` and `group_by="observation_type"`; groups carry representative `observation_id`/`trace_id`.
- `get_error_count` returns `exception_count: null` with `count_basis: "error_level_observations"` — individual exception events are not retrievable from the standard observation listing.
- Detail records gain `level`/`observation_type`/`status_message`; `event_id`/`event_name` are retained but always null; exception fields are null when not recorded in metadata (top-level keys take precedence over `metadata.attributes`).


## [0.10.2] - 2026-09-09
### Fixed
- `fetch_observations` accepts every Langfuse observation type (`AGENT`, `TOOL`, `CHAIN`, `RETRIEVER`, `EVALUATOR`, `EMBEDDING`, `GUARDRAIL` as well as `SPAN`, `GENERATION`, `EVENT`).

### Changed
- README first screen states the product, last-month PyPI downloads, and version. The native comparison is a local-debug vs hosted lane picker.
- README lead now puts live GitHub stars and PyPI monthly-download badges next to each other, cites pypistats for last-month usage, answers why this vs native Langfuse MCP first, and documents the existing exception-tool path for a failing trace.
- Migrated from MCP Python SDK 1.x (`FastMCP`) to 2.x (`MCPServer`). The runtime pin is now `mcp[cli]>=2,<3`. HTTP bind address and port are passed to `run(transport="streamable-http", ...)` instead of the server constructor.


## [0.10.1] - 2026-08-06
### Fixed
- Constrained the MCP SDK below 2.0 and added a clean installed-wheel startup smoke so fresh `uvx langfuse-mcp` installs no longer resolve an incompatible SDK that removed `mcp.server.fastmcp` (closes #67).


## [0.10.0] - 2026-06-27
### Added
- **Streamable HTTP transport** (`--transport streamable-http`): run a single persistent
  server instance that serves multiple MCP clients over HTTP, eliminating the need for
  one process/container per project.
  - `--bind-host` (default `127.0.0.1`) and `--port` (default `8000`) control the
    listening address. Expose on `0.0.0.0` only behind a TLS-terminating,
    authenticating reverse-proxy or within a trusted network.
  - `LANGFUSE_MCP_BIND_HOST` and `LANGFUSE_MCP_PORT` env-var counterparts.
- **Per-request project credentials via `Authorization: Basic`**: pass
  `Authorization: Basic <base64(public_key:secret_key)>` on each HTTP request to
  target a specific Langfuse project. Absent header falls back to startup env
  credentials; any malformed value is rejected (fail closed — no silent fallback).
  Per-project clients are cached in a bounded LRU (max 32 entries); evicted clients
  are flushed and shut down to prevent resource leaks.
- **`LANGFUSE_MCP_TRACE_TIMEOUT_SECONDS`** (default `120`): per-request read timeout
  in seconds for single-trace fetches (`fetch_trace`). Raise it if large traces with
  `include_observations=True` time out.

### Changed
- **`fetch_trace` scopes the `GET /traces/{id}` request via a `fields` selector.** The
  endpoint returns every field group by default (`core,io,scores,observations,metrics`);
  for traces with many observations that pulls each observation's full IO — often
  megabytes — which is the main cause of read timeouts. `fetch_trace` now drops the
  `observations` field group unless `include_observations=True` (so `include_observations=False`
  no longer returns observation references), and raises the per-request read timeout for
  single-trace fetches. The `fields` selector is forwarded through SDK request options so
  it works on the supported `langfuse>=3.11.2` floor. Falls back to a plain `get()` only
  on older SDKs that do not accept `request_options`.


## [0.9.1] - 2026-05-06
### Changed
- Re-enabled Python 3.14 support now that the supported Langfuse SDK range includes v4, which uses Pydantic v2; CI now covers Python 3.10 through 3.14.


## [0.9.0] - 2026-04-29
### Changed
- Allow `langfuse>=4.0.0,<5.0.0` alongside the existing `>=3.11.2,<4.0.0` range so projects can pin langfuse-mcp without blocking the v4.x SDK upgrade (closes #40).
- Added a small capability-based shim (`langfuse_mcp/_compat.py`) so MCP tool calls auto-select the right SDK surface across SDK versions:
  - Score list/get routing now follows the `api.scores` (v4) ↔ `api.score_v_2` (v3) rename, and the v4 method rename `get` → `get_many`. Score creation tools are unchanged.
  - Annotation queue write tools now branch between v3's `request=<PydanticModel>` style and v4's direct-kwargs style. Path identifiers (`queue_id`, `item_id`) are passed as keyword args in both branches.
  - Single observation fetch precedence is `api.observations.get` (v3) → `api.legacy.observations_v1.get` (v4 self-host safe) → top-level `client.fetch_observation` shim.
- `fetch_observations` keeps its existing `page` + `limit` MCP schema. On v4 deployments where only the cursor-based `observations_v2` route is exposed, requests for `page > 1` raise an explicit `ERR_LANGFUSE_OBSERVATIONS_CURSOR_PAGE_UNSUPPORTED` error pointing at `legacy.observations_v1` rather than silently returning page 1.
- `_extract_items_from_response` now preserves `meta` pagination on responses with `data + meta` (previously dropped on the `.data` branch).

### Notes
- v4 adds `opentelemetry-api`, `opentelemetry-sdk`, and `opentelemetry-exporter-otlp-proto-http` as transitive dependencies. langfuse-mcp instantiates the client with `tracing_enabled=False`, so no traces are emitted by default.
- Real-SDK smoke verification: live `Langfuse` import + `_compat` dispatcher selection probed against `langfuse==3.14.5` and `langfuse==4.5.1` for the observation list/fetch paths. The annotation queue, dataset, dataset-item, and score paths are verified by source-level signature inspection of `langfuse-python` v4.0.6 and the corresponding v3 SDK; runtime exercise lives in v3-shape and strict-v4-shape fakes that mirror the real SDK signatures (no `**kwargs` permissiveness on v4 write methods).


## [0.8.0] - 2026-04-28
### Added
- `LANGFUSE_MAX_AGE_DAYS` env var lets deployments override the 7-day lookback cap on time-based tools (`fetch_traces`, `fetch_observations`, `find_exceptions`, `get_user_sessions`, etc.) to match longer Langfuse retention windows. Tool schema descriptions now reflect the configured cap.


## [0.7.0] - 2026-04-26
### Added
- Added `--default-output-mode` and `LANGFUSE_MCP_DEFAULT_OUTPUT_MODE` so MCP tool schemas can default to `compact`, `full_json_string`, or `full_json_file` when clients omit `output_mode`.

### Fixed
- Consolidated PyPI, Docker, and skill publishing into the release workflow so they no longer depend on tag-push events that `GITHUB_TOKEN` cannot trigger.
- Pinned all GitHub Actions to commit SHAs across every workflow for supply-chain safety.
- Added missing `permissions`, `timeout-minutes`, and `concurrency` blocks to all workflows.
- Standalone publish workflows now accept `workflow_dispatch` with an explicit `tag` input and check out the tag ref, making manual reruns safe regardless of branch context.


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
