FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-venv \
    make \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install CI tools the project depends on (available for the agent to run diagnostics)
RUN pip3 install ruff==0.4.4 mypy==1.10.0 pyyaml==6.0.2 types-PyYAML==6.0.12.20240917

COPY app/ /app/

WORKDIR /app
