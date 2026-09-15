FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


# Install Java for TLC/SANY model checker, plus python3 for scripts
RUN apt-get update && apt-get install -y --no-install-recommends \
        openjdk-21-jdk-headless \
        python3-pip \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Download TLA+ tools (SANY parser + TLC model checker)
RUN curl -fsSL -o /opt/tla2tools.jar \
    "https://github.com/tlaplus/tlaplus/releases/download/v1.8.0/tla2tools.jar"

# Set up the task workspace with buggy specifications
RUN mkdir -p /app/spec
COPY ticket_lock.tla /app/spec/ticket_lock.tla
COPY ticket_lock.cfg /app/spec/ticket_lock.cfg
COPY rwlock.tla /app/spec/rwlock.tla
COPY rwlock.cfg /app/spec/rwlock.cfg

WORKDIR /app
