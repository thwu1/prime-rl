FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    wget \
    curl \
    jq \
    file \
    && rm -rf /var/lib/apt/lists/*

COPY design/ /opt/soc_design/

RUN ls /opt/soc_design/rtl/gpio_bank.sv /opt/soc_design/pkg/soc_pkg.sv /opt/soc_design/include/soc_config.svh

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
