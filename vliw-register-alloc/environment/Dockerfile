FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip gcc graphviz && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/tools /app/output

COPY vliw.py /app/vliw.py
COPY programs.py /app/programs.py
COPY backend.py /app/backend.py
COPY vsim.c /app/tools/vsim.c
COPY vexport.py /app/tools/vexport.py
COPY vdot.py /app/tools/vdot.py

RUN chmod +x /app/tools/vexport.py /app/tools/vdot.py

WORKDIR /app
