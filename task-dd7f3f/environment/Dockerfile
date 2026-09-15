
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN if [ -f /etc/apt/sources.list.d/ubuntu.sources ]; then \
      grep -q 'universe' /etc/apt/sources.list.d/ubuntu.sources || \
        sed -i '/^Components:/ s/$/ universe/' /etc/apt/sources.list.d/ubuntu.sources; \
    elif [ -f /etc/apt/sources.list ]; then \
      grep -q 'universe' /etc/apt/sources.list || \
        sed -i 's/main$/main universe/' /etc/apt/sources.list; \
    fi && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        build-essential \
        minisat \
        glpk-utils \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/instances /app/output /app/sat /app/ilp

COPY instances/ /app/instances/

WORKDIR /app
