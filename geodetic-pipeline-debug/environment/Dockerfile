FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y proj-bin proj-data python3-pip && \
    rm -rf /var/lib/apt/lists/*

COPY transforms.gie /app/transforms.gie
COPY calibration_setup.py /tmp/calibration_setup.py
RUN python3 /tmp/calibration_setup.py && rm /tmp/calibration_setup.py
WORKDIR /app
