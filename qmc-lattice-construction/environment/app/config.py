"""Configuration for the QMC lattice rule benchmark."""

DIMENSION = 10
COEFFICIENTS = [1.0 / j for j in range(1, DIMENSION + 1)]
WEIGHTS = [1.0 / (j ** 2) for j in range(1, DIMENSION + 1)]
CONVERGENCE_PRIMES = [251, 509, 1021, 2053, 4099, 8209]
N_SHIFTS = 30
SEED = 12345
