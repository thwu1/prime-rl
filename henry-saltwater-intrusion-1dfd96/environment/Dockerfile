FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    gfortran \
    meson \
    ninja-build \
    wget \
    unzip \
    curl \
    && rm -rf /var/lib/apt/lists/*


WORKDIR /app
COPY parameters.json /app/parameters.json
COPY build_model.py /app/build_model.py
COPY postprocess.py /app/postprocess.py
RUN mkdir -p /app/model
