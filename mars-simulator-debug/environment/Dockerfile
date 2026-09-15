
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 python3-pip build-essential git && \
    rm -rf /var/lib/apt/lists/*

# Build pMARS from source (SERVER mode = no graphics dependencies)
RUN git clone --depth 1 https://github.com/mbarbon/pMARS.git /tmp/pmars && \
    cd /tmp/pmars/src && \
    make CFLAGS="-O2 -DEXT94 -DPERMUTATE -DRWLIMIT -DSERVER" LIB="" LFLAGS="" && \
    cp pmars /usr/local/bin/ && \
    rm -rf /tmp/pmars

# Set up directories
RUN mkdir -p /app/opponents

# Copy opponent warriors
COPY imp.red /app/opponents/imp.red
COPY dwarf.red /app/opponents/dwarf.red
COPY stone.red /app/opponents/stone.red
COPY scanner.red /app/opponents/scanner.red
COPY splitter.red /app/opponents/splitter.red

WORKDIR /app
