# syntax=docker/dockerfile:1
# Langfuse MCP Server — Docker image
# Builds an image that runs the MCP server over stdio for use as a Goose Command-line Extension.

FROM python:3.11-slim

# Install runtime OS packages (curl for debugging optional)
RUN apt-get update -y && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Create app user
RUN useradd -ms /bin/bash appuser
USER appuser
WORKDIR /home/appuser/app

# Copy project source into the image so we can install the current tree.
COPY --chown=appuser:appuser . ./

# Install the local checkout (editable isn't needed inside the container).
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

# Default environment — keep stdout clean for MCP stdio, log to file
ENV LANGFUSE_LOG_LEVEL=INFO \
    LANGFUSE_LOG_TO_CONSOLE=false \
    PYTHONUNBUFFERED=1

# Expose no ports (stdio-based MCP)
# ENTRYPOINT runs the MCP server over stdio. Do not add --log-to-console.
ENTRYPOINT ["python", "-m", "langfuse_mcp"]

# Default CMD can set a dump dir if desired. Users can override via args.
CMD ["--dump-dir", "/dumps"]
