FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV PYBAMM_DISABLE_TELEMETRY=true


RUN apt-get update && \
    apt-get install -y python3 python3-pip python3-dev build-essential && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install pybamm==25.12.2 numpy==1.26.4 scipy==1.14.1 --no-cache-dir -q

RUN mkdir -p /root/.config/pybamm && \
    echo "pybamm:" > /root/.config/pybamm/config.yml && \
    echo "  enable_telemetry: false" >> /root/.config/pybamm/config.yml

RUN mkdir -p /app
WORKDIR /app
