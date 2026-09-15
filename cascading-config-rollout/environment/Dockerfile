
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        jq \
        make \
        strace \
        time \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /opt/task/config_pipeline /opt/task/data /app/config_pipeline /app/data

COPY config_pipeline/ /opt/task/config_pipeline/
COPY run_simulation.py /opt/task/run_simulation.py
COPY incident.log /opt/task/data/incident.log
COPY incident_events.json /opt/task/data/incident_events.json
COPY Makefile /opt/task/Makefile

RUN cp -r /opt/task/config_pipeline/* /app/config_pipeline/ && \
    cp /opt/task/run_simulation.py /app/run_simulation.py && \
    cp /opt/task/data/incident.log /app/data/incident.log && \
    cp /opt/task/data/incident_events.json /app/data/incident_events.json && \
    cp /opt/task/Makefile /app/Makefile

WORKDIR /app
