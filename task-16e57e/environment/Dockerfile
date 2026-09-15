FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip sqlite3 octave && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY newton_schulz.py /app/newton_schulz.py
COPY create_db.py /tmp/create_db.py
COPY create_mat.m /tmp/create_mat.m

RUN pip3 install numpy==2.1.3 -q && python3 /tmp/create_db.py && octave-cli --silent /tmp/create_mat.m && rm /tmp/create_db.py /tmp/create_mat.m

WORKDIR /app
