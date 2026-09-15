FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip python3-dev && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==1.26.4 pandas==2.2.3 scikit-learn==1.5.2 mlflow==2.15.1

WORKDIR /app

COPY monitoring_policy.yaml /app/config/monitoring_policy.yaml
COPY deployment_config.yaml /app/config/deployment_config.yaml
COPY setup_data.py /tmp/setup_data.py
RUN python3 /tmp/setup_data.py && rm /tmp/setup_data.py

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 scipy==1.13.1
