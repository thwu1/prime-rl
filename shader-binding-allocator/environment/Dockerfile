FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    glslang-tools \
    g++ \
    curl \
    make \
    && rm -rf /var/lib/apt/lists/*

# Build spirv-cross CLI from source (Makefile-based build avoids cmake issues in containers)
RUN curl -sL https://github.com/KhronosGroup/SPIRV-Cross/archive/refs/tags/vulkan-sdk-1.3.290.0.tar.gz -o /tmp/sc.tar.gz && \
    tar xzf /tmp/sc.tar.gz -C /tmp && \
    cd /tmp/SPIRV-Cross-vulkan-sdk-1.3.290.0 && \
    make -j$(nproc) && \
    cp spirv-cross /usr/local/bin/ && \
    rm -rf /tmp/SPIRV-Cross-vulkan-sdk-1.3.290.0 /tmp/sc.tar.gz

# Verify spirv-cross is installed and executable
RUN which spirv-cross && spirv-cross --help > /dev/null 2>&1 || true

RUN mkdir -p /app/docs /app/shaders

COPY docs/pipeline_spec.md /app/docs/pipeline_spec.md
COPY docs/binding_rules.md /app/docs/binding_rules.md
COPY shaders/particles.glsl /app/shaders/particles.glsl
COPY shaders/scene.glsl /app/shaders/scene.glsl

WORKDIR /app
