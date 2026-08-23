FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MPLCONFIGDIR=/tmp/matplotlib

RUN apt-get update \
    && apt-get install --no-install-recommends -y fonts-arphic-ukai \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home app

WORKDIR /app

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY alembic.ini ./
COPY migrations ./migrations
COPY ashare_agent ./ashare_agent

RUN mkdir -p /app/.artifacts/charts /tmp/matplotlib \
    && chown -R app:app /app/.artifacts /tmp/matplotlib

USER app

EXPOSE 8000

CMD ["uvicorn", "ashare_agent.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
