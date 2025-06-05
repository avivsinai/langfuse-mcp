# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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