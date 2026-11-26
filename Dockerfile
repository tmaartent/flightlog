# syntax=docker/dockerfile:1
# Flightlog's images (ADR-0017). Two targets from one file:
#   runtime  the app (gunicorn), the worker and the migrations: no browser
#   report   runtime plus headless Chromium, for `flask report` only (about 500 MB more)

# --- builder: every wheel, built once, so the runtime image needs no compiler or pip cache --
FROM python:3.13-slim AS builder
WORKDIR /src
COPY pyproject.toml ./
COPY src ./src
RUN pip wheel --no-cache-dir --wheel-dir /wheels .

# --- runtime ----------------------------------------------------------------------------------
FROM python:3.13-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
RUN --mount=type=bind,from=builder,source=/wheels,target=/wheels \
    pip install --no-index --find-links=/wheels flightlog \
    && useradd --uid 10001 --create-home --shell /usr/sbin/nologin flightlog
WORKDIR /app
# Alembic reads alembic.ini and migrations/ from here; the package itself is installed.
COPY alembic.ini ./
COPY migrations ./migrations
USER flightlog
EXPOSE 8000
# A list, not a shell line: gunicorn is PID 1 and gets docker's SIGTERM itself.
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "4", \
     "--access-logfile", "-", "flightlog:create_app()"]

# --- report -----------------------------------------------------------------------------------
FROM runtime AS report
USER root
# Browsers in a shared path, installed as root with their system libraries, used as flightlog.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
# Playwright's own Node needs libatomic1 just to start, before it can install anything else.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libatomic1 \
    && playwright install --with-deps --only-shell chromium \
    && rm -rf /var/lib/apt/lists/*
USER flightlog
ENTRYPOINT ["flask", "--app", "flightlog", "report"]
