FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==2.1.3

COPY setup_data.py /tmp/setup_data.py
RUN python3 /tmp/setup_data.py

# --- Final stage: task environment only ---
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip sqlite3 xmlstarlet xxd jq && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/config /app/telemetry /app/calibration /app/logs

COPY --from=builder /tmp/flight_test.db /app/telemetry/flight_test.db
COPY --from=builder /tmp/thrust_cal.dat /app/calibration/thrust_cal.dat
COPY config/frame.param /app/config/frame.param
COPY config/vehicle.urdf /app/config/vehicle.urdf
COPY calibration/FORMAT.md /app/calibration/FORMAT.md
COPY logs/controller.log /app/logs/controller.log
COPY mission_notes.txt /app/mission_notes.txt

WORKDIR /app
