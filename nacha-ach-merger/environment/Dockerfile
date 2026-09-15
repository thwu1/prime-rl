FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y golang python3-pip && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY go.mod main.go ach.go parser.go merge.go validator.go addenda.go writer.go /app/
