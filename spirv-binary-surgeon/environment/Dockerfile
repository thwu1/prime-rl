
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 python3-pip \
    glslang-tools spirv-tools \
    && rm -rf /var/lib/apt/lists/*

COPY shaders/ /app/shaders/

RUN mkdir -p /app/modules && \
    glslangValidator -V -o /app/modules/vertex.spv /app/shaders/vertex.vert && \
    glslangValidator -V -o /app/modules/fragment.spv /app/shaders/fragment.frag && \
    glslangValidator -V -o /app/modules/compute.spv /app/shaders/compute.comp && \
    spirv-as --target-env vulkan1.0 /app/shaders/custom.spvasm -o /app/modules/custom.spv && \
    spirv-val /app/modules/vertex.spv && \
    spirv-val /app/modules/fragment.spv && \
    spirv-val /app/modules/compute.spv && \
    spirv-val /app/modules/custom.spv

COPY remap_config.json /app/remap_config.json

WORKDIR /app
