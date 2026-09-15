FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/raw/forecasts /app/docs /app/pipeline /app/results

COPY events.jsonl /app/raw/events.jsonl
COPY outcomes.csv /app/raw/outcomes.csv
COPY forecasts_atlas.json /app/raw/forecasts/atlas.json
COPY forecasts_beacon.json /app/raw/forecasts/beacon.json
COPY forecasts_cipher.json /app/raw/forecasts/cipher.json
COPY forecasts_drift.json /app/raw/forecasts/drift.json
COPY forecasts_echo.json /app/raw/forecasts/echo.json
COPY forecasts_flux.json /app/raw/forecasts/flux.json

COPY config.yaml /app/config.yaml
COPY methodology.md /app/docs/methodology.md
COPY developer_notes.txt /app/docs/developer_notes.txt
COPY evaluate_legacy.py /app/pipeline/evaluate.py

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 numpy==2.1.3 scipy==1.14.1
