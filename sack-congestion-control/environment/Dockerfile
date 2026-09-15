FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /opt/starter /app

COPY packet.py /opt/starter/packet.py
COPY emulator.py /opt/starter/emulator.py
COPY run_transfer.py /opt/starter/run_transfer.py
COPY sender.py /opt/starter/sender.py
COPY receiver.py /opt/starter/receiver.py

RUN cp /opt/starter/*.py /app/

WORKDIR /app
