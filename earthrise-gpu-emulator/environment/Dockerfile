FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY hardware/ /app/hardware/
COPY docs/ /app/docs/
COPY programs/ /app/programs/

RUN ls /app/hardware/ && ls /app/docs/ && ls /app/programs/

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 pluggy==1.6.0
