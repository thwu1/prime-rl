FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install cryptography==43.0.3

RUN mkdir -p /app/implementations
WORKDIR /app

COPY impl_alpha.py /app/implementations/impl_alpha.py
COPY impl_beta.py /app/implementations/impl_beta.py
COPY impl_gamma.py /app/implementations/impl_gamma.py
COPY impl_delta.py /app/implementations/impl_delta.py
COPY impl_epsilon.py /app/implementations/impl_epsilon.py

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 cryptography==43.0.3
