FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends golang-go python3-pip && \
    rm -rf /var/lib/apt/lists/*


RUN mkdir -p /app/gobdecode /app/testdata

COPY testgen.mod /app/go.mod
COPY generate_tests.go /app/generate_tests.go
COPY gobdecode/main.go /app/gobdecode/main.go
COPY gobdecode/go.mod /app/gobdecode/go.mod

WORKDIR /app
