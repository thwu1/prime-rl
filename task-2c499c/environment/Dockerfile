# Stage 1 — build: export model & generate reference data (needs PyTorch)
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    libglib2.0-0 \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

# Install CPU-only PyTorch first (~200MB vs ~2GB for CUDA version)
RUN pip3 install --no-cache-dir torch==2.3.1 torchvision==0.18.1 \
    --index-url https://download.pytorch.org/whl/cpu

# Install ultralytics (sees torch already present, won't reinstall) and other deps
RUN pip3 install --no-cache-dir \
    ultralytics==8.2.0 \
    onnxruntime==1.19.2 \
    opencv-python-headless==4.10.0.84 \
    numpy==1.26.4 \
    onnx==1.16.1

COPY setup_env.py /tmp/setup_env.py
COPY pipeline_template.py /tmp/pipeline_template.py
RUN python3 /tmp/setup_env.py

# Stage 2 — runtime: slim image with only onnxruntime (no PyTorch / ultralytics)
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    libglib2.0-0 \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir \
    onnxruntime==1.19.2 \
    opencv-python-headless==4.10.0.84 \
    numpy==1.26.4

COPY --from=builder /app /app
WORKDIR /app
