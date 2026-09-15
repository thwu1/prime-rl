"""Run MCMC inference for the HMM model."""
import sys
import numpy as np
import jax.numpy as jnp
from jax import random

import numpyro
from numpyro.infer import MCMC, NUTS

from hmm_model import hmm_model


def main():
    K = int(sys.argv[1]) if len(sys.argv) > 1 else 3

    # Load training data — experiment_1 only
    train_obs = jnp.array(np.load("/app/data/experiment_1/obs.npy"))
    print(f"Loaded {train_obs.shape[0]} sequences from experiment_1")

    numpyro.set_host_device_count(1)
    kernel = NUTS(hmm_model)
    mcmc = MCMC(kernel, num_warmup=300, num_samples=500, num_chains=1)
    mcmc.run(random.key(42), train_obs, K)
    mcmc.print_summary()

    # Report divergences
    diverging = mcmc.get_extra_fields()["diverging"]
    n_div = int(jnp.sum(diverging))
    print(f"\nNumber of divergences: {n_div}")


if __name__ == "__main__":
    main()
