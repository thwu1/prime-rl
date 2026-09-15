FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    git \
    wget \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Install Go 1.23
RUN wget -q https://go.dev/dl/go1.23.4.linux-amd64.tar.gz && \
    tar -C /usr/local -xzf go1.23.4.linux-amd64.tar.gz && \
    rm go1.23.4.linux-amd64.tar.gz

ENV PATH="/usr/local/go/bin:/root/go/bin:${PATH}"
ENV GOPATH="/root/go"

# Clone the Monkey language implementation
RUN git clone https://github.com/bradford-hamilton/monkey-lang.git /app

WORKDIR /app

# Pre-fetch Go module dependencies
RUN go mod download

# Add verification test file for while loops
COPY while_loop_test.go /app/vm/while_loop_test.go

# Verify existing code builds
RUN go build ./...
