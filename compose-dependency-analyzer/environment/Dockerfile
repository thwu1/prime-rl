FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY docker-compose.yml /app/docker-compose.yml
COPY docker-compose.prod.yml /app/docker-compose.prod.yml
COPY .env /app/.env
COPY .env.prod /app/.env.prod

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 pyyaml==6.0.2
