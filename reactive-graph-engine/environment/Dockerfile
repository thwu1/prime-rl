
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV GOTOOLCHAIN=local
ENV GOPATH="/root/go"

RUN apt-get update && apt-get install -y \
    python3-pip \
    wget \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN ARCH=$(dpkg --print-architecture) && \
    wget -q "https://go.dev/dl/go1.22.5.linux-${ARCH}.tar.gz" -O /tmp/go.tar.gz && \
    tar -C /usr/local -xzf /tmp/go.tar.gz && \
    rm /tmp/go.tar.gz

ENV PATH="/usr/local/go/bin:/root/go/bin:${PATH}"

COPY app/ /app/

WORKDIR /app
RUN go version && go build ./...
