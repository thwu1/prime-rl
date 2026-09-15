FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*


RUN mkdir -p /app/data

COPY data/sample-issue-140.pdb /app/data/sample-issue-140.pdb
COPY data/3SGB.pdb /app/data/3SGB.pdb
COPY data/1HPX.pdb /app/data/1HPX.pdb
COPY data/propka.cfg /app/data/propka.cfg

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 propka==3.5.1
