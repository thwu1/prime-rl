FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    git \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==1.26.4 scipy==1.13.1

RUN pip3 install --no-deps git+https://github.com/sandialabs/cross-sim.git@v3.2.1

WORKDIR /app

COPY device_datasheet.md /app/device_datasheet.md
