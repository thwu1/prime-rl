FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    calculix-ccx \
    && rm -rf /var/lib/apt/lists/*

# Create symlink so 'ccx' works (package may install as ccx_2.xx)
RUN if [ ! -f /usr/bin/ccx ] && ls /usr/bin/ccx_* 1>/dev/null 2>&1; then \
        ln -s /usr/bin/ccx_* /usr/bin/ccx; \
    fi

RUN mkdir -p /app
COPY le10_abaqus.inp /app/le10_abaqus.inp
