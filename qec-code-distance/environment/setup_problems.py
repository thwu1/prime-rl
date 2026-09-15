"""Generate example detector error model files for the QEC code distance task."""
import stim
import os

os.makedirs("/app/problems", exist_ok=True)

# Repetition code examples
for d in [3, 5]:
    c = stim.Circuit.generated(
        "repetition_code:memory",
        rounds=d,
        distance=d,
        after_clifford_depolarization=0.01,
    )
    dem = c.detector_error_model(decompose_errors=True)
    with open(f"/app/problems/rep_d{d}.dem", "w") as f:
        print(dem, file=f)

# Surface code example
c = stim.Circuit.generated(
    "surface_code:rotated_memory_z",
    rounds=3,
    distance=3,
    after_clifford_depolarization=0.001,
)
dem = c.detector_error_model(decompose_errors=True)
with open("/app/problems/surface_d3.dem", "w") as f:
    print(dem, file=f)

# Hand-crafted chain example (distance 3)
with open("/app/problems/custom_chain_d3.dem", "w") as f:
    f.write("error(0.1) D0 L0\n")
    f.write("error(0.1) D0 D1\n")
    f.write("error(0.1) D1\n")
