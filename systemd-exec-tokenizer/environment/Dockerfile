FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    systemd \
    python3-pip \
    curl \
    && rm -rf /var/lib/apt/lists/*


COPY argv_inspector.sh /app/bin/argv_inspector.sh
RUN chmod +x /app/bin/argv_inspector.sh

COPY units/ /app/units/
COPY specs/ /app/specs/

WORKDIR /app
