FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip jq && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/rust_src/transform

COPY ir.json /app/ir.json
COPY transforms.yaml /app/transforms.yaml
COPY rust_src/ir.rs /app/rust_src/ir.rs
COPY rust_src/validate.rs /app/rust_src/validate.rs
COPY rust_src/transform/common.rs /app/rust_src/transform/common.rs
COPY rust_src/transform/mod.rs /app/rust_src/transform/mod.rs
COPY rust_src/transform/sanitize.rs /app/rust_src/transform/sanitize.rs
COPY rust_src/transform/rename.rs /app/rust_src/transform/rename.rs
COPY rust_src/transform/rename_fields.rs /app/rust_src/transform/rename_fields.rs
COPY rust_src/transform/merge_enums.rs /app/rust_src/transform/merge_enums.rs
COPY rust_src/transform/merge_fieldsets.rs /app/rust_src/transform/merge_fieldsets.rs
COPY rust_src/transform/make_block.rs /app/rust_src/transform/make_block.rs
COPY rust_src/transform/make_register_array.rs /app/rust_src/transform/make_register_array.rs
COPY rust_src/transform/delete_registers.rs /app/rust_src/transform/delete_registers.rs
COPY rust_src/transform/delete_fieldsets.rs /app/rust_src/transform/delete_fieldsets.rs
COPY rust_src/transform/delete_enums.rs /app/rust_src/transform/delete_enums.rs

WORKDIR /app
