
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    cmake \
    g++ \
    make \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/src /app/data /app/build /app/output

COPY gen_data.py /tmp/gen_data.py
RUN python3 /tmp/gen_data.py && rm /tmp/gen_data.py

COPY CMakeLists.txt /app/CMakeLists.txt
COPY float_tool_skeleton.cpp /app/src/float_tool.cpp
COPY manifest.json /app/manifest.json

RUN test -f /app/data/vectors/base_values.bin && echo "Binary data verified"
RUN test -f /app/data/samples/lab_readings.txt && echo "Text data verified"
RUN test -f /app/data/imports/eu_sensor_data.csv && echo "CSV data verified"
RUN test -f /app/data/reference/ieee754_hex.txt && echo "Hex data verified"
RUN test -f /app/data/archive/constants.json && echo "JSON data verified"

WORKDIR /app
