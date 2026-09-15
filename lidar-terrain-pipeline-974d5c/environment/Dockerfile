FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3-pip \
        python3-numpy \
        python3-scipy \
        gdal-bin \
        python3-gdal \
    && rm -rf /var/lib/apt/lists/*


COPY generate_input.py /app/generate_input.py
COPY config.json /app/config.json

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 laspy==2.5.4
