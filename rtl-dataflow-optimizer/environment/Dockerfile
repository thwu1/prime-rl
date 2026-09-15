FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip make graphviz && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/programs

COPY rtl.py /app/rtl.py
COPY programs/poly_eval.json /app/programs/poly_eval.json
COPY programs/const_arith.json /app/programs/const_arith.json
COPY programs/dead_triangle.json /app/programs/dead_triangle.json
COPY programs/branch_const.json /app/programs/branch_const.json
COPY programs/cascade.json /app/programs/cascade.json
COPY programs/loop_constprop.json /app/programs/loop_constprop.json
COPY programs/nested_diamond.json /app/programs/nested_diamond.json
COPY programs/strength_chain.json /app/programs/strength_chain.json

WORKDIR /app
