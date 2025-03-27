# Contributing to Langfuse MCP

Thank you for your interest in contributing to Langfuse MCP! This guide will help you get started.

## Development Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/avivsinai/langfuse-mcp.git
   cd langfuse-mcp
   ```

2. We use `uv` for package management. Make sure it's installed:
   ```bash
   curl -sSf https://astral.sh/uv/install.sh | bash
   ```

3. Install development dependencies:
   ```bash
   uv pip install -e ".[dev]"
   ```

## Making Changes

1. Create a branch for your changes:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. Make your changes and write tests if applicable

3. Run tests to ensure everything is working:
   ```bash
   uv run -m pytest
   ```

4. Format your code with Ruff:
   ```bash
   uv run -m ruff format .
   uv run -m ruff check --fix .
   ```

## Submitting Changes

1. Push your changes to your fork:
   ```bash
   git push origin feature/your-feature-name
   ```

2. Create a pull request on GitHub

3. In your PR description, clearly explain:
   - What changes you've made
   - Why you've made them
   - Any additional context that might help reviewers

## Adding New MCP Tools

When adding new tools to interact with Langfuse:

1. Add the tool function in the appropriate module
2. Update tool documentation in the README
3. Add tests for the new tool functionality
4. Update examples if applicable

## Code Style

- Use type hints for all function parameters and return values
- Write docstrings for all functions following the Google docstring format
- Follow PEP 8 guidelines (handled by Ruff)
- Keep functions focused and small
- Name variables and functions clearly

## License

By contributing to this project, you agree that your contributions will be licensed under the project's MIT license. 