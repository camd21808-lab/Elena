FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-dejavu-core curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt && \
    playwright install chromium --with-deps

COPY engine ./engine
COPY api ./api
COPY cli ./cli
COPY .env.example ./.env

ENV SCANDE_SYSTEM_CHROME=false \
    SCANDE_QUEUE=redis \
    SCANDE_LOCAL_ROOT=/data/de-thi

VOLUME ["/data"]

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
