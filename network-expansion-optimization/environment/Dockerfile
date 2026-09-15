
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Clone OWA EPANET and compile directly with gcc to avoid cmake libuv
# assertion crashes (uv__close fd > STDERR_FILENO) in podman containers
RUN git clone --depth 1 https://github.com/OpenWaterAnalytics/EPANET.git /opt/epanet-src && \
    cd /opt/epanet-src && \
    SRC_DIR=$(find . -maxdepth 3 -name 'epanet.c' -not -path '*/test*' -exec dirname {} \; | head -n1) && \
    RUN_FILE=$(find . -maxdepth 3 -name 'main.c' -not -path '*/test*' | head -n1) && \
    test -n "$SRC_DIR" && test -n "$RUN_FILE" && \
    echo "Building EPANET: sources=$SRC_DIR main=$RUN_FILE" && \
    gcc -O2 -fPIC -shared -Iinclude "$SRC_DIR"/*.c -lm -o libepanet2.so && \
    gcc -O2 -Iinclude -o runepanet "$RUN_FILE" -L. -lepanet2 -lm -Wl,-rpath,/usr/local/lib && \
    cp runepanet /usr/local/bin/ && \
    cp libepanet2.so /usr/local/lib/ && \
    ldconfig && \
    rm -rf /opt/epanet-src

ENV LD_LIBRARY_PATH=/usr/local/lib

WORKDIR /app

COPY network.inp /app/network.inp
COPY expansion_spec.json /app/expansion_spec.json
COPY pipe_catalog.json /app/pipe_catalog.json
