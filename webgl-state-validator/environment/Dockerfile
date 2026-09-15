FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    glslang-tools \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/shaders

COPY gl_constants.py /app/gl_constants.py
COPY state_types.py /app/state_types.py
COPY validator.py /app/validator.py
COPY shader_analyzer.py /app/shader_analyzer.py
COPY conformance_check.py /app/conformance_check.py
COPY init_db.py /app/init_db.py
COPY spec_reference.md /app/spec_reference.md
COPY shaders/basic.vert /app/shaders/basic.vert
COPY shaders/basic.frag /app/shaders/basic.frag
COPY shaders/multitex.frag /app/shaders/multitex.frag
COPY shaders/invalid.frag /app/shaders/invalid.frag

RUN python3 /app/init_db.py

WORKDIR /app
