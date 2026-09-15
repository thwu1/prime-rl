FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    glslang-tools \
    spirv-tools \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/shaders

COPY basic.glsl /app/shaders/basic.glsl
COPY lighting.glsl /app/shaders/lighting.glsl
COPY compute.glsl /app/shaders/compute.glsl
COPY pathological.glsl /app/shaders/pathological.glsl
COPY multipass.glsl /app/shaders/multipass.glsl
COPY spec.md /app/SPEC.md

WORKDIR /app
