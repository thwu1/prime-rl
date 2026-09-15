
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    default-jre-headless \
    wget \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Download TLA+ tools (TLC model checker)
RUN wget -q https://github.com/tlaplus/tlaplus/releases/download/v1.8.0/tla2tools.jar \
    -O /usr/local/lib/tla2tools.jar

WORKDIR /app

# Copy the buggy specification and TLC configuration
COPY VotingProtocol.tla /app/VotingProtocol.tla
COPY VotingProtocol.cfg /app/VotingProtocol.cfg
