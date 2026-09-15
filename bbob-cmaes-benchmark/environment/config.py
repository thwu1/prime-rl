"""
COCO BBOB Experiment Configuration.

Defines the benchmark suite parameters for evaluating black-box optimizers.
Refer to the BBOB noiseless function definitions for properties of each
function ID (see the COCO platform documentation).
"""

# COCO suite specification
SUITE_NAME = "bbob"
INSTANCE_SPEC = "instances: 1-3"

# Selected BBOB function IDs for this experiment
FUNCTION_IDS = [1, 2, 3, 8, 10, 11, 12, 15]

# Dimensions to evaluate
DIMENSIONS = [2, 5, 10]

# Evaluation budget per problem: BUDGET_FACTOR * dimension
BUDGET_FACTOR = 20000
