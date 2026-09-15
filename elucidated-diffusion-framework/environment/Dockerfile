FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y --no-install-recommends python3-pip python3 && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir torch==2.5.1+cpu --index-url https://download.pytorch.org/whl/cpu
RUN pip3 install --no-cache-dir einops==0.8.0 tqdm==4.66.5

RUN mkdir -p /app

COPY helpers.py /app/helpers.py
COPY unet.py /app/unet.py
COPY spec.md /app/spec.md
COPY diffusion.py /app/diffusion.py

WORKDIR /app
