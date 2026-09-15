FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y \
        python3-pip \
        spirv-tools \
        glslang-tools \
        spirv-cross \
    && rm -rf /var/lib/apt/lists/*

COPY shaders/ /app/shaders/
COPY platform_profiles.json /app/platform_profiles.json
RUN mkdir -p /app/output
WORKDIR /app
