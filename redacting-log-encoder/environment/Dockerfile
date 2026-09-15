FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y golang-go python3-pip && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/redact

COPY app/go.mod /app/go.mod
COPY app/redact/config.go /app/redact/config.go
COPY app/redact/encoder.go /app/redact/encoder.go


WORKDIR /app
