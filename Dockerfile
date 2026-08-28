FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim AS base

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Install scc from official release
RUN curl -fsSL https://github.com/boyter/scc/releases/download/v3.3.0/scc_3.3.0_Linux_x86_64.tar.gz -o /tmp/scc.tar.gz \
    && tar -xzf /tmp/scc.tar.gz -C /usr/local/bin scc \
    && rm /tmp/scc.tar.gz \
    && chmod +x /usr/local/bin/scc

WORKDIR /app

# Layer caching: dependencies first (copied separately from source code)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# Then copy source code and install the project itself
COPY scopio ./scopio
COPY README.md ./
RUN uv sync --frozen --no-dev

ENV PATH=/app/.venv/bin:$PATH

ENTRYPOINT ["scopio"]
CMD ["--help"]
