# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: percent
# ---

# %% [markdown]
# # QPE with Linear Combination of Unitaries
#
# Reference tutorial from qpe-toolbox demonstrating LCU-based qubitization QPE.
# NOT runnable in this environment — provided as algorithmic reference only.

# %% [markdown]
# The Linear Combination of Unitaries approach begins by rewriting the Hamiltonian
# into a sum of unitaries:
#
# $$ H = \sum_{\ell=0}^{L-1} w_\ell H_\ell \qquad \mathrm{s.t.} \qquad w_\ell \geq 0, \qquad H_\ell^2 = \mathbb{1}, $$
#
# where $H_\ell^2 = \mathbb{1}$ expresses the condition that $H_\ell$ is hermitian and unitary.
#
# The weights $w_\ell$ are defined to be positive. If needed the phase of $w_\ell$ can
# always be absorbed by a re-definition of the unitary $H_\ell$.
#
# We define the sum of weights, often referred to as the "1-norm" of the LCU:
#
# $$ \lambda \equiv \sum_{\ell=0}^{L-1} w_\ell $$
#
# We then introduce an empty ancilla register of size $m_L$
#
# $$ m_L \equiv \lceil{ \mathrm{log}_2 (L) \rceil}$$
#
# In the case where $L < 2^{m_L}$ we complete the weights up to $2^{m_L}$ by setting
#
# $$ w_\ell = 0,~H_\ell = \mathbb{1} \qquad \mathrm{for}~ L \leq \ell < 2^{m_L}.$$

# %% [markdown]
# ## PREPARE oracle
# The PREPARE oracle acts on the $m_L$ qubits of the auxiliary $\ell$-register
# to prepare a superposition state related to the LCU decomposition:
#
# $$ \mathrm{PREPARE} \equiv \sum_{\ell=0}^{L-1} \sqrt{\frac{w_\ell}{\lambda}} \ket{\ell}\bra{0} $$
#
# The state prepared by the action of the PREPARE oracle is called
# the $\ket{\mathcal{L}}$ state:
#
# $$ \mathrm{PREPARE} \ket{0}^{\otimes m_L} \mapsto \sum_{\ell=0}^{L-1} \sqrt{\frac{w_\ell}{\lambda}} \ket{\ell} \equiv \ket{\mathcal{L}} $$

# %% [markdown]
# ## SELECT oracle
#
# The SELECT oracle is a unitary operation acting on both the auxiliary
# $\ell$-register and the physical register:
#
# $$ \mathrm{SELECT} \equiv \sum_{\ell=0}^{L-1} |\ell\rangle \langle \ell| \otimes H_\ell, $$
#
# Note that for any $\ket{\psi}$ we have:
#
# $$ \bra{\psi}\bra{\mathcal{L}} \mathrm{SELECT} \ket{\mathcal{L}}\ket{\psi} = \bra{\psi}\frac{H}{\lambda}\ket{\psi} $$
#
# i.e. the combination of SELECT and PREPARE gives an encoding of the Hamiltonian.

# %% [markdown]
# ## Walk operator
# The Walk operator is defined by
#
# $$ \mathcal{W} = \mathcal{R}_L \cdot \mathrm{SELECT}, \qquad \mathcal{R}_L \equiv \left(2 \ket{\mathcal{L}} \bra{\mathcal{L}} \otimes \mathbb{1} - \mathbb{1} \right) $$
#
# For an eigenstate $\ket{\psi_k}$ with eigenvalue $E_k$, the action of
# $\mathcal{W}$ on $\ket{\mathcal{L}}\ket{\psi_k}$ spans a two-dimensional
# space. In the basis $\{ \ket{\mathcal{L}}\ket{\psi_k}, \ket{\phi_k} \}$,
# the Walk operator reads
#
# $$ \mathcal{W} = e^{i \arccos\left({E_k/\lambda}\right) Y} $$
#
# Its eigenphases are exact functions of the energy $E_k$. We can therefore
# apply the QPE algorithm on $\mathcal{W}$ to find $E_k$.

# %% [markdown]
# ## QPE on Walk operator
#
# The energy is recovered from the eigenphase:
#
# $$ 2 \pi \theta = \pm \arccos(E_0/\lambda) \implies E_0 = \cos(2 \pi \theta) \cdot \lambda $$
#
# The precision on $E$ is:
#
# $$ \Delta E = \lambda \frac{2\pi}{2^m} \sqrt{1 - \left(\frac{E_0}{\lambda}\right)^2} $$

# %% Example usage (requires qpe-toolbox + quimb, not available here)
#
# import qpe_toolbox.estimation as qpe
# from qpe_toolbox.hamiltonian import heisenberg_hamiltonian, do_dmrg
#
# H = heisenberg_hamiltonian(4)
# weights, lmb, L, m_L = qpe.get_lcu_weights(H)
# E0, psi0 = do_dmrg(H)
#
# traces, theta = qpe.run_qpe_lcu_walk_operator(H, psi0, n_phase_qubits=4)
# energy = qpe.get_energy_from_lcu_walk_phase(theta, lmb)
# error_bound = qpe.estimate_lcu_error(n_phase_qubits, E0, lmb)
