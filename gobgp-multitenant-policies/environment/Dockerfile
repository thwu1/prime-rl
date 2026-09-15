FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    wget \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Install Go (needed to build GoBGP from source)
RUN wget -q https://go.dev/dl/go1.22.5.linux-amd64.tar.gz -O /tmp/go.tar.gz && \
    tar -C /usr/local -xzf /tmp/go.tar.gz && \
    rm /tmp/go.tar.gz
ENV PATH=$PATH:/usr/local/go/bin GOPATH=/opt/go GOTOOLCHAIN=auto

# Install GoBGP binaries
RUN go install github.com/osrg/gobgp/v4/cmd/gobgp@latest && \
    go install github.com/osrg/gobgp/v4/cmd/gobgpd@latest && \
    cp $GOPATH/bin/gobgp /usr/local/bin/ && \
    cp $GOPATH/bin/gobgpd /usr/local/bin/

# Extract proto files from Go module cache using find (robust against version strings)
RUN mkdir -p /app/proto/api && \
    GOBGP_API=$(find $GOPATH/pkg/mod -type d -path "*/osrg/gobgp/v*/api" | head -1) && \
    test -n "$GOBGP_API" && \
    cp "$GOBGP_API"/*.proto /app/proto/api/ && \
    chmod -R 755 /app/proto && \
    ls /app/proto/api/*.proto

# Install grpcio and protobuf (task environment: agent needs these to use the gRPC API)
# Pre-compile Python gRPC stubs from proto definitions
RUN pip3 install grpcio==1.62.2 grpcio-tools==1.62.2 protobuf==4.25.3 && \
    mkdir -p /app/generated/api && \
    python3 -m grpc_tools.protoc \
        -I/app/proto \
        --python_out=/app/generated \
        --grpc_python_out=/app/generated \
        /app/proto/api/*.proto && \
    touch /app/generated/__init__.py /app/generated/api/__init__.py

# Clean up Go toolchain (no longer needed at runtime)
RUN rm -rf /usr/local/go $GOPATH /root/.cache/go-build /root/sdk
ENV PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

COPY tenants.json /app/tenants.json
COPY state_schema.json /app/state_schema.json

WORKDIR /app
