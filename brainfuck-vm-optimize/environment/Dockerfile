
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    golang-go \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY go.mod /app/go.mod
COPY instruction.go /app/instruction.go
COPY compiler.go /app/compiler.go
COPY machine.go /app/machine.go
COPY main.go /app/main.go

COPY testdata/ /app/testdata/

RUN go build -o /app/bfvm /app/
