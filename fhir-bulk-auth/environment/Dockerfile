FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip curl && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /opt/task-setup /opt/task-data/spec

COPY setup/init_environment.py /opt/task-setup/init_environment.py
COPY spec/requirements.md /opt/task-data/spec/requirements.md

RUN pip3 install cryptography==44.0.0 -q
RUN python3 /opt/task-setup/init_environment.py

# Copy generated instance data + spec into /app for the agent's starting state.
# Also kept at /opt/task-data/ as a durable backup for runtime restoration.
RUN mkdir -p /app && \
    cp -r /opt/task-data/config /app/config && \
    cp -r /opt/task-data/data /app/data && \
    cp -r /opt/task-data/spec /app/spec

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 requests==2.32.3 PyJWT==2.9.0 cryptography==44.0.0
