FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/graphs /app/instances /app/mystery_instances /app/encodings /app/solutions

COPY graphs/ /app/graphs/
COPY instances/ /app/instances/
COPY mystery_instances/ /app/mystery_instances/
COPY format_spec.txt /app/format_spec.txt

WORKDIR /app
