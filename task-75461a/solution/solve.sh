#!/bin/bash

pip3 install pyyaml==6.0.2 toml==0.10.2 -q

# Generate the Flux TOML configuration from the cluster specification
python3 /solution/generate_config.py
