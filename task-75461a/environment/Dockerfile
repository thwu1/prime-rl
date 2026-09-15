FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    curl \
    wget \
    jq \
    ca-certificates \
    bzip2 \
    && rm -rf /var/lib/apt/lists/*

# Install Miniforge3 (conda-forge based package manager)
RUN curl -L -o /tmp/miniforge.sh \
    "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh" && \
    bash /tmp/miniforge.sh -b -p /opt/conda && \
    rm /tmp/miniforge.sh

ENV PATH="/opt/conda/bin:$PATH"

# Install flux-core from conda-forge (pinned version)
RUN conda install -y -c conda-forge flux-core=0.86.0 && \
    conda clean --all --yes

# Copy cluster specification into the task environment
COPY cluster_spec.yaml /app/cluster_spec.yaml

# Create config directory for the agent to write into
RUN mkdir -p /app/flux_config

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 toml==0.10.2
