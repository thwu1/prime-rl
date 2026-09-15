FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y --no-install-recommends python3 python3-pip make gnuplot-nox && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==2.1.3 --break-system-packages -q

RUN mkdir -p /app/reference_data /app/tools /app/output

COPY app/README.md /app/README.md
COPY app/Makefile /app/Makefile
COPY app/elliptic_filter.py /app/elliptic_filter.py
COPY app/tools/validate.py /app/tools/validate.py
COPY app/tools/filterspec.py /app/tools/filterspec.py
COPY app/reference_data/order3_rp3.0_rs30.json /app/reference_data/order3_rp3.0_rs30.json
COPY app/reference_data/order4_rp0.5_rs60.json /app/reference_data/order4_rp0.5_rs60.json
COPY app/reference_data/order5_rp1.0_rs40.json /app/reference_data/order5_rp1.0_rs40.json
COPY app/reference_data/order7_rp0.1_rs80.json /app/reference_data/order7_rp0.1_rs80.json

WORKDIR /app
