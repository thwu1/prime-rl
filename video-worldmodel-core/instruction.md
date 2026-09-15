The `/app/` directory contains a partially implemented inference pipeline for a 3D video diffusion transformer. Six interdependent computational modules in `/app/video_wm/` are stubbed — each function raises `NotImplementedError`.

Each stub file has function signatures with type annotations and docstrings. Project documentation and a validation tool are in `/app/`. Model parameters are in `/app/config.py`.

Implement all six modules so that `python3 /app/validate.py` exits with code 0.