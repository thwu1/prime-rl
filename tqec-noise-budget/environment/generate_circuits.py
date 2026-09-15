"""Generate noisy rotated surface code memory circuits for the task."""
import stim
import json
import os

os.makedirs("/app", exist_ok=True)

params = {
    "code_task": "surface_code:rotated_memory_z",
    "rounds": 3,
    "noise_level": 0.001,
    "distances": [3, 5],
}

for d in params["distances"]:
    circuit = stim.Circuit.generated(
        params["code_task"],
        rounds=params["rounds"],
        distance=d,
        after_clifford_depolarization=params["noise_level"],
        after_reset_flip_probability=params["noise_level"],
        before_measure_flip_probability=params["noise_level"],
        before_round_data_depolarization=params["noise_level"],
    )
    with open(f"/app/circuit_d{d}.stim", "w") as f:
        f.write(str(circuit))

with open("/app/circuit_params.json", "w") as f:
    json.dump(params, f, indent=2)

print(f"Generated circuits: d=3 ({os.path.getsize('/app/circuit_d3.stim')} bytes), "
      f"d=5 ({os.path.getsize('/app/circuit_d5.stim')} bytes)")
