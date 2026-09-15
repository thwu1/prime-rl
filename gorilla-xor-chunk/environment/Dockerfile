FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y golang python3-pip && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY go.mod /app/go.mod
COPY bstream.go /app/bstream.go
COPY chunk.go /app/chunk.go
COPY xor.go /app/xor.go
COPY varbit.go /app/varbit.go
COPY merge.go /app/merge.go
