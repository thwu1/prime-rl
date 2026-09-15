FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip build-essential && rm -rf /var/lib/apt/lists/*

RUN pip3 install torch==2.5.1 --index-url https://download.pytorch.org/whl/cpu

RUN rm -rf /app
COPY app/ /app/

WORKDIR /app

# Verify config is importable at build time
RUN python3 -c "import sys; sys.path.insert(0, '/app'); from glm5_config import GLM5Config; c = GLM5Config(); print('GLM5Config OK:', c.hidden_size, c.qk_head_dim)"

# Verify C toolchain is available
RUN gcc --version && make --version
