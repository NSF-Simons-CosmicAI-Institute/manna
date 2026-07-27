# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS builder
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /build

# Install uv (frozen version pinned for reproducibility — bump deliberately)
RUN pip install --no-cache-dir "uv==0.4.30"

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src/ ./src/
COPY README.md ./
# --no-editable installs the project as a real wheel into .venv site-packages,
# instead of as an editable install that hardcodes /build/src paths. The
# runtime stage works from /app/ so the editable path would be broken.
RUN uv sync --frozen --no-dev --no-editable


FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

RUN useradd --create-home --shell /usr/sbin/nologin --uid 10001 mcp
WORKDIR /app
COPY --from=builder /build/.venv ./.venv
COPY --from=builder /build/src ./src

USER mcp
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health',timeout=3).status==200 else 1)"

CMD ["python", "-m", "manna"]
