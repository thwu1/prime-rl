import stim
import numpy as np
import json
import os

os.makedirs("/app", exist_ok=True)

d = 5
p = 0.01
circuit = stim.Circuit.generated(
    "surface_code:rotated_memory_x",
    rounds=d,
    distance=d,
    before_round_data_depolarization=p,
    before_measure_flip_probability=p,
    after_reset_flip_probability=p,
    after_clifford_depolarization=p,
)
circuit.to_file("/app/surface_code.stim")

dem = circuit.detector_error_model(decompose_errors=True)
dem.to_file("/app/surface_code.dem")

num_shots = 500
sampler = circuit.compile_detector_sampler(seed=42)
shot_data = sampler.sample(
    num_shots, separate_observables=False, append_observables=True
)
stim.write_shot_data_file(
    data=shot_data,
    path="/app/shots.b8",
    format="b8",
    num_detectors=dem.num_detectors,
    num_observables=dem.num_observables,
)

config = {
    "num_detectors": dem.num_detectors,
    "num_observables": dem.num_observables,
    "num_shots": num_shots,
    "distance": d,
    "noise_rate": p,
    "rounds": d,
}
with open("/app/config.json", "w") as f:
    json.dump(config, f, indent=2)
