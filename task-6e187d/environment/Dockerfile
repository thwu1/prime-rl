FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    python3-pip \
    python3-dev \
    jq \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install yamllint==1.35.1 pyyaml==6.0.2

WORKDIR /app

COPY nav2_params_broken.yaml /app/nav2_params_broken.yaml
COPY robot_spec.json /app/robot_spec.json
COPY sim_logs/ /app/sim_logs/
COPY tools/ /app/tools/

RUN chmod +x /app/tools/validate_nav2.py

