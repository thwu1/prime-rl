FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/instances
COPY instances/berlin52.tsp /app/instances/berlin52.tsp
COPY instances/att48.tsp /app/instances/att48.tsp
COPY instances/br17.atsp /app/instances/br17.atsp
COPY instances/eil22.vrp /app/instances/eil22.vrp
COPY instances/eil13.vrp /app/instances/eil13.vrp

WORKDIR /app
