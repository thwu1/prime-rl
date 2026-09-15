The directory `/app/` is a git repository containing `rotation_toolkit.py`, a NumPy-based 3D rotation library covering quaternion/matrix/axis-angle conversions, geodesic distance on SO(3), SLERP, Karcher mean, and SVD projection to SO(3).

The main branch has mathematical bugs in three existing functions and four unimplemented stubs that raise `NotImplementedError`. Two feature branches (`candidate-alpha` and `candidate-beta`) each provide implementations for all four stub functions, but each branch contains a mix of correct and subtly flawed code. No single branch has all correct implementations.

Fix the bugs in the existing functions. Evaluate the competing implementations from both candidate branches to determine which is mathematically correct for each stub function. Integrate the correct implementation for each into the toolkit on the main branch.

Write `/app/evaluation.json` documenting your assessment. It must contain an entry for each of the four stub functions with keys `"selected"` (value `"alpha"` or `"beta"`) and `"reason"` (brief justification for why that candidate's implementation is correct and the other is flawed).

The final `/app/rotation_toolkit.py` and `/app/evaluation.json` must both be correct.