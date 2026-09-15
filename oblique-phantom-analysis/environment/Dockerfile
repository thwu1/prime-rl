FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install itk==5.4.0 numpy==2.1.3

RUN mkdir -p /app

COPY calibration_spec.json /app/calibration_spec.json
COPY generate_phantom.py /tmp/generate_phantom.py

RUN python3 /tmp/generate_phantom.py && rm /tmp/generate_phantom.py

WORKDIR /app
