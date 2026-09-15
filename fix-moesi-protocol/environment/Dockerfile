FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        gcc \
        make \
        libc6-dev \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/coherence_sim

# Copy C extension source and build the shared library
COPY sim_src/coherence_sim/addr_calc.c /app/coherence_sim/addr_calc.c
COPY sim_src/coherence_sim/Makefile /app/coherence_sim/Makefile
RUN make -C /app/coherence_sim

# Copy Python sources
COPY sim_src/coherence_sim/__init__.py /app/coherence_sim/__init__.py
COPY sim_src/coherence_sim/types.py /app/coherence_sim/types.py
COPY sim_src/coherence_sim/l1_controller.py /app/coherence_sim/l1_controller.py
COPY sim_src/coherence_sim/l2_controller.py /app/coherence_sim/l2_controller.py
COPY sim_src/coherence_sim/cache_bank.py /app/coherence_sim/cache_bank.py
COPY sim_src/coherence_sim/directory_controller.py /app/coherence_sim/directory_controller.py
COPY sim_src/coherence_sim/memory_system.py /app/coherence_sim/memory_system.py
COPY sim_src/coherence_sim/simulator.py /app/coherence_sim/simulator.py
COPY sim_src/run_workload.py /app/run_workload.py

WORKDIR /app
