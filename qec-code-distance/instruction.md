Implement `/app/compute_distance.py` — a tool that computes the code distance of a quantum error correcting code from its Stim detector error model (`.dem` file).

The code distance is the minimum number of independent error mechanisms whose combined effect flips at least one logical observable without triggering any detector. Formally: find a minimum-cardinality subset S of `error` instructions such that the symmetric difference of their detector target sets is empty and the symmetric difference of their observable target sets is non-empty.

Your tool must:
- Accept a single command-line argument: path to a `.dem` file
- Print a single integer to stdout: the computed code distance
- Handle error models with `repeat` blocks and `shift_detectors` instructions (use Stim's API to flatten)
- Handle error instructions containing separator (`^`) targets by XOR-ing detector/observable targets across chunks
- Handle models with multiple logical observables (report the minimum distance across all observables)
- Handle both errors connecting pairs of detectors and errors connecting a single detector to the implicit boundary node

Stim is pre-installed. Example `.dem` files are in `/app/problems/` for development and testing. The examples include detector error models extracted from repetition codes and surface codes of various distances.