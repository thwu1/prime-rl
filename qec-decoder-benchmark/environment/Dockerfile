FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/output

RUN python3 -c 'import json; json.dump({"code":"surface_code:rotated_memory_x","distance":3,"rounds":9,"noise":{"after_clifford_depolarization":0.003,"before_measure_flip_probability":0.003,"before_round_data_depolarization":0.003,"after_reset_flip_probability":0.003}}, open("/app/data/circuit_config.json","w"), indent=2)'

WORKDIR /app
