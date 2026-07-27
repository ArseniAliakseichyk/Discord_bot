# Audio is handled by the Lavalink service, so the bot image stays minimal
# (no ffmpeg / PyNaCl needed).
FROM python:3.12-slim

# The container writes the SQLite database into the bind-mounted ./data, so this
# uid/gid must match the host user that owns it. Override at build time if yours
# differs: docker compose build --build-arg UID=$(id -u) --build-arg GID=$(id -g)
ARG UID=1000
ARG GID=1000

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run unprivileged rather than as root.
RUN groupadd --gid "${GID}" botuser \
    && useradd --create-home --uid "${UID}" --gid "${GID}" botuser \
    && mkdir -p /app/data \
    && chown -R "${UID}:${GID}" /app
USER botuser

# Cheap liveness signal for compose: the process is up and imports still resolve.
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import config"]

CMD ["python", "bot.py"]
