FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip sqlite3 gnuplot-nox && rm -rf /var/lib/apt/lists/*

RUN pip3 install h5py==3.12.1

COPY generate_trajectories.py /setup/generate_trajectories.py
COPY format.md /setup/format.md
COPY config.toml /setup/config.toml

RUN mkdir -p /app/data /app/reports /app/plots && \
    python3 /setup/generate_trajectories.py && \
    cp /setup/format.md /app/data/FORMAT.md && \
    cp /setup/config.toml /app/config.toml && \
    rm -rf /setup

WORKDIR /app
