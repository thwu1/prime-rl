FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    golang-go \
    python3-pip \
    protobuf-compiler \
    && rm -rf /var/lib/apt/lists/*


WORKDIR /app

COPY go.mod main.go wire.go codec.go schema.go merge.go ./
COPY testdata/ testdata/
