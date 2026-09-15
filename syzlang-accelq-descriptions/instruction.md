Two engineers independently wrote syzkaller syzlang syscall descriptions to fuzz the `/dev/accelq` hardware accelerator queue driver. Both pass syz-check syntax validation, but both achieve near-zero kernel driver coverage after 48 hours of fuzzing (see `/app/coverage_report.txt`).

- Candidate A: `/app/candidate_a.txt`
- Candidate B: `/app/candidate_b.txt`
- Kernel UAPI header: `/app/header/accelq.h`
- Interface specification: `/app/interface_spec.txt`

Each candidate makes different modeling decisions — some correct, some wrong. Neither is fully correct. The descriptions differ in at least 10 semantic aspects affecting fuzzing effectiveness.

Evaluate both candidates against the kernel header and interface spec to determine which candidate correctly models each aspect, then produce the correct descriptions.

**Deliverables:**

`/app/evaluation.json` — A JSON object with the following keys. Each value must be an object with `"correct"` (`"A"` or `"B"`) indicating which candidate models that aspect correctly, and `"explanation"` (string) describing why:

- `include_path` — header include directive path
- `buf_handle_base_type` — buffer handle resource base type width
- `create_ctx_ptr_direction` — pointer direction for the CREATE_CTX ioctl
- `ctx_id_resource_production` — ctx_id resource annotation in the create struct
- `queue_id_resource_production` — queue_id resource annotation in the create struct
- `submit_args_field_order` — field ordering in accelq_submit_args
- `descs_ptr_type_modeling` — how the descriptor array pointer is modeled
- `nr_descs_length_annotation` — whether nr_descs uses a length annotation
- `descriptor_op_flag_reference` — which flag set the descriptor op field references
- `descriptor_handle_resource_types` — whether descriptor handles use resource types

`/app/accelq.txt` — Correct unified syzlang descriptions incorporating the right modeling decision from each candidate for every aspect.