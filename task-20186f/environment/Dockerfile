
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip default-jre-headless curl && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/spec /app/scenarios /app/tools /app/expected

RUN curl -fSL -o /app/tools/tla2tools.jar \
    https://github.com/tlaplus/tlaplus/releases/download/v1.8.0/tla2tools.jar

COPY spec/kip966.tla /app/spec/kip966.tla
COPY spec/kip966.cfg /app/spec/kip966.cfg

COPY run_scenario.py /app/run_scenario.py
COPY scenarios/ /app/scenarios/

COPY expected/ /app/expected/

WORKDIR /app
