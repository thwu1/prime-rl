FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    gcc \
    binutils \
    gdb \
    strace \
    ltrace \
    netcat-openbsd \
    python3-pip \
    procps \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy and compile the ground station server
COPY ground_station.c /tmp/ground_station.c
RUN gcc -o /app/ground_station /tmp/ground_station.c -Wall -O2 && \
    rm /tmp/ground_station.c && \
    chmod +x /app/ground_station

# Copy telemetry query script
COPY telem_query.sh /app/telem_query
RUN chmod +x /app/telem_query

# Copy partial protocol specification (for the agent to analyze)
RUN mkdir -p /app/docs
COPY protocol_spec.md /app/docs/protocol_spec.md

# Create secrets directory (flag is generated at runtime, not baked into image)
RUN mkdir -p /app/secrets

# Copy startup script
COPY start_server.sh /app/start_server.sh
RUN chmod +x /app/start_server.sh

CMD ["/bin/bash", "/app/start_server.sh"]
