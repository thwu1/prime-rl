
FROM golang:1.22-bookworm AS builder
COPY src/main.go /build/main.go
WORKDIR /build
RUN go mod init graphtool && CGO_ENABLED=0 go build -ldflags="-s -w" -o /graphtool .

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
RUN apt-get update && apt-get install -y python3-pip xxd strace && rm -rf /var/lib/apt/lists/*
COPY --from=builder /graphtool /app/ref_tool
WORKDIR /app
