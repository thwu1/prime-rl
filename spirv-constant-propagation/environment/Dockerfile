FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3 python3-pip spirv-tools && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/shaders

COPY shaders/ /app/shaders/
COPY expected.json /app/expected.json
COPY sample.spvasm /app/sample.spvasm

RUN cd /app/shaders && spirv-as phi_merge.spvasm -o phi_merge.spv && rm phi_merge.spvasm && spirv-as switch_case.spvasm -o switch_case.spv && rm switch_case.spvasm && spirv-as logic_chain.spvasm -o logic_chain.spv && rm logic_chain.spvasm

WORKDIR /app
