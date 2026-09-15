FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    graphviz \
    jq \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install pyyaml==6.0.2

COPY app/reference.md /app/reference.md
COPY app/containerlab_src/ /app/containerlab_src/
COPY app/pods/ /app/pods/
COPY app/federation_specs/ /app/federation_specs/

WORKDIR /app
