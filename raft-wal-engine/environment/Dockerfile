FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder

RUN apt-get update && apt-get install -y golang-go python3 && rm -rf /var/lib/apt/lists/*

COPY gowal/ /build/gowal/
COPY cluster_setup.py /build/cluster_setup.py

WORKDIR /build/gowal
RUN go build -o /build/gowal/gowal .

RUN python3 /build/cluster_setup.py /build/cluster

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip golang-go xxd && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/gowal /app/cluster

COPY --from=builder /build/gowal/main.go /app/gowal/main.go
COPY --from=builder /build/gowal/wal.go /app/gowal/wal.go
COPY --from=builder /build/gowal/go.mod /app/gowal/go.mod
COPY --from=builder /build/gowal/gowal /app/gowal/gowal
COPY --from=builder /build/cluster/ /app/cluster/

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
