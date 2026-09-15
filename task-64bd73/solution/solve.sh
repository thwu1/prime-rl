#!/bin/bash

pip3 install numpy==2.1.3 -q

# Generate and write the optimizer implementation
python3 /solution/generate_solution.py

# Generate the validation pipeline (extract_and_validate.sh + validate_helper.py)
python3 /solution/generate_validation.py

# Run the validation pipeline
/app/extract_and_validate.sh
