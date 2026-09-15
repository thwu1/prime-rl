A compiled stochastic simulator binary at `/app/simulator` maps 2D parameters θ ∈ [-1,1]² to 2D observations x. It accepts and produces raw binary float64 files — run `/app/simulator --help` for the full interface specification. The simulator has no tractable likelihood function, precluding standard MCMC.

Three observed datasets are stored in `/app/observations.h5` (HDF5 format) as datasets `obs_1`, `obs_2`, `obs_3` (shape `(1,2)` each). File-level HDF5 attributes contain the prior bounds and task metadata. Command-line HDF5 tools `h5dump` and `h5ls` are available, as is the `h5py` Python library.

Implement a likelihood-free inference method from first principles to approximate the posterior distribution p(θ|x) for each observation. You must interface with the compiled simulator binary for all forward simulations — it is the only implementation of the generative model. Write input parameters as raw binary float64 files, invoke the binary, and parse its binary output.

Save your results as an HDF5 file at `/app/results/posteriors.h5` containing datasets `posterior_1`, `posterior_2`, `posterior_3`, each with shape `(10000, 2)`.

Quality is evaluated via the Classifier Two-Sample Test (C2ST): a binary classifier is trained to distinguish your samples from reference samples drawn from the true posterior. C2ST ≈ 0.5 means indistinguishable; C2ST ≈ 1.0 means perfectly separable. **All three observations must achieve C2ST < 0.57.**

Constraints: do not use pre-built simulation-based inference packages (e.g., `sbi`, `pyabc`, `elfi`). Implement your method using standard scientific computing tools.