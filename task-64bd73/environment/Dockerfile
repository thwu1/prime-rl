FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip sqlite3 jq && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY simulator.py hamiltonian.py optimizer.py create_reference_db.py /app/
RUN python3 /app/create_reference_db.py && rm /app/create_reference_db.py
