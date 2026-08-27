# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    MPLBACKEND=Agg \
    MPLCONFIGDIR=/tmp/matplotlib \
    APP_CONFIG_PATH=/home/appuser/.secrets/app_config.json

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY crypto_backtest /app/crypto_backtest

# Run as an unprivileged user; /data is the mount point for generated outputs.
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /data /home/appuser/.secrets \
    && chown -R appuser:appuser /data /home/appuser

USER appuser
WORKDIR /data

ENTRYPOINT ["python", "-m", "crypto_backtest.cli"]
CMD ["run"]
