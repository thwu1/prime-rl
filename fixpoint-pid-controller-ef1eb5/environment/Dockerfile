FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    gcc \
    make \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*


COPY fixpoint.h /app/fixpoint.h
COPY plant.h /app/plant.h
COPY plant.c /app/plant.c
COPY pid_controller.h /app/pid_controller.h
COPY pid_controller.c /app/pid_controller.c
COPY sim_harness.c /app/sim_harness.c
COPY Makefile /app/Makefile
COPY sim_params.h /app/sim_params.h

WORKDIR /app
