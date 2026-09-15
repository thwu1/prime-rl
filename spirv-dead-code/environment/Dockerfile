FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    spirv-tools \
    spirv-headers \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/modules

COPY simple.spvasm /tmp/spvasm/simple.spvasm
COPY dead_computation.spvasm /tmp/spvasm/dead_computation.spvasm
COPY dead_function.spvasm /tmp/spvasm/dead_function.spvasm
COPY complex_dead.spvasm /tmp/spvasm/complex_dead.spvasm

RUN cd /tmp/spvasm && \
    spirv-as --target-env spv1.3 simple.spvasm -o /app/modules/simple.spv && \
    spirv-as --target-env spv1.3 dead_computation.spvasm -o /app/modules/dead_computation.spv && \
    spirv-as --target-env spv1.3 dead_function.spvasm -o /app/modules/dead_function.spv && \
    spirv-as --target-env spv1.3 complex_dead.spvasm -o /app/modules/complex_dead.spv && \
    spirv-val --target-env spv1.3 /app/modules/simple.spv && \
    spirv-val --target-env spv1.3 /app/modules/dead_computation.spv && \
    spirv-val --target-env spv1.3 /app/modules/dead_function.spv && \
    spirv-val --target-env spv1.3 /app/modules/complex_dead.spv && \
    rm -rf /tmp/spvasm

WORKDIR /app
