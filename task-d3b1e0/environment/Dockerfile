FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y golang python3-pip && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY go.mod /app/go.mod
COPY main.go /app/main.go
RUN cd /app && go mod tidy && go build -o /dev/null

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
