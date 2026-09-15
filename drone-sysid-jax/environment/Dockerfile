FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==2.1.3 -q

COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py && rm /tmp/generate_data.py

COPY dynamics_spec.md /app/dynamics_spec.md
COPY known_params.json /app/data/known_params.json
COPY sim_params.json /app/data/sim_params.json
COPY simulator.py /app/simulator.py

RUN mkdir -p /app/results

WORKDIR /app

