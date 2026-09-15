FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    openssl jq curl ca-certificates golang-go git python3-pip && \
    rm -rf /var/lib/apt/lists/*

# Install cosign v2.4.1
RUN curl -fsSL https://github.com/sigstore/cosign/releases/download/v2.4.1/cosign-linux-amd64 \
    -o /usr/local/bin/cosign && chmod +x /usr/local/bin/cosign

# Install crane from go-containerregistry v0.20.2
RUN curl -fsSL https://github.com/google/go-containerregistry/releases/download/v0.20.2/go-containerregistry_Linux_x86_64.tar.gz | \
    tar xz -C /usr/local/bin crane

# Build and install the in-memory OCI registry from go-containerregistry
RUN export GOPATH=/tmp/gopath && \
    CGO_ENABLED=0 go install github.com/google/go-containerregistry/cmd/registry@v0.20.2 && \
    mv /tmp/gopath/bin/registry /usr/local/bin/registry && \
    rm -rf /tmp/gopath /root/.cache/go-build /root/go

WORKDIR /app

# Set up broken initial pipeline state for diagnosis
COPY setup_broken.sh /tmp/setup_broken.sh
RUN bash /tmp/setup_broken.sh && rm /tmp/setup_broken.sh
