FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3 && rm -rf /var/lib/apt/lists/*

COPY generate_reference.py /tmp/generate_reference.py
RUN python3 /tmp/generate_reference.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 python3-pip gcc make gnuplot-nox jq \
    && rm -rf /var/lib/apt/lists/*

COPY lib/ /app/lib/
RUN cd /app/lib && make

COPY engine.py /app/engine.py
COPY config/ /app/config/
COPY simulations/ /app/simulations/
COPY tools/ /app/tools/
COPY --from=builder /app/reference/ /app/reference/
RUN mkdir -p /app/output

WORKDIR /app
