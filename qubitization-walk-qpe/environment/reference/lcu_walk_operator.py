# --------------------------------------------------------------------------------------
# This file is part of qpe-toolbox.
#
# SPDX-License-Identifier: Apache-2.0
# Licensed under the Apache License, Version 2.0. See LICENSE.txt and NOTICE.txt in the
# project root.
#
# Reference implementation of LCU walk operator construction and QPE energy extraction.
# Uses quimb tensor networks (MPS/MPO) — NOT runnable in this environment, provided
# as algorithmic reference only.
# --------------------------------------------------------------------------------------

import itertools
import time

import numpy as np
import quimb as qu
import quimb.tensor as qtn

from qpe_toolbox.circuit import shift_control_gates
from qpe_toolbox.tensor import apply_gate_from_mpo, controlled_mpo, kron_mpos, kron_mps

from .qft import iqft_swapped

#####################################
### L register and PREPARE oracle ###
#####################################


def get_lcu_weights(hamiltonian):
    """
    Compute the LCU weights, normalization factor, and ancilla register size for a Hamiltonian.

    Parameters
    ----------
    hamiltonian : Hamiltonian
        Hamiltonian from the QPE-Toolbox ``Hamiltonian`` class.

    Returns
    -------
    weights : list of float
        Absolute values of the Hamiltonian coefficients, extended with zeros to
        match a power-of-two length.
    lmb : float
        Sum of absolute values of Hamiltonian coefficients (normalization factor).
    L : int
        Number of original Hamiltonian terms.
    m_L : int
        Number of qubits required for the auxiliary L-register,
        i.e., ``ceil(log2(L))``.
    """
    weights = [abs(P[0]) for P in hamiltonian.terms]

    lmb = sum(weights)
    L = len(weights)
    if L < 2:
        raise ValueError("Need at least 2 terms in Hamiltonian")

    # number of ancilla qubits for the PREPARE oracle
    m_L = int(np.ceil(np.log2(L)))
    # complete the weights with zeros when L is not a power of 2
    weights.extend([0] * (2**m_L - L))
    return weights, lmb, L, m_L


def build_lcu_prepare_state_mps(hamiltonian, *, cutoff=1e-10):
    r"""
    Construct the normalized MPS representing the L register state :math:`\ket{\mathcal{L}}`.

    .. math::
        \ket{\mathcal{L}} = \sum_\ell \sqrt{\frac{w_\ell}{\lambda}} \ket{\ell}

    Parameters
    ----------
    hamiltonian : Hamiltonian
        Hamiltonian to encode with LCU.
    cutoff : float, default ``1e-10``
        Singular value cutoff for MPS compression.

    Returns
    -------
    L_mps : MatrixProductState
        MPS representing the state :math:`\ket{\mathcal{L}}`.
    """
    weights, lmb, L, m_L = get_lcu_weights(hamiltonian)

    # Initialize |L> state MPS
    L_mps = np.sqrt(weights[0] / lmb) * qtn.MPS_computational_state("0" * m_L)
    for i in range(1, L):
        L_mps += np.sqrt(weights[i] / lmb) * qtn.MPS_computational_state(f"{i:0{m_L}b}")
    # Check normalization
    if not np.isclose(L_mps.norm(), 1.0, atol=cutoff):
        raise ValueError("Invalid MPS normalization")
    L_mps.compress(cutoff=cutoff)
    return L_mps


###############################################################################
##################### SELECT oracle ###########################################
###############################################################################


# MPO representation of SELECT oracle
def _build_Hl_mpo(hamiltonian, l_term):
    r"""
    Build MPO for the l-th Pauli string of a Hamiltonian.

    Parameters
    ----------
    hamiltonian : Hamiltonian
        Hamiltonian describing the system.
    l_term : int
        Index of the Hamiltonian term.

    Returns
    -------
    Hl_mpo : MatrixProductOperator
        MPO representing the l-th term of the Hamiltonian.
    """
    if l_term >= len(hamiltonian.terms):
        return qtn.MPO_identity(hamiltonian.n_qubits)
    if hamiltonian.terms[l_term][0] == 0:
        return qtn.MPO_identity(hamiltonian.n_qubits)

    P = hamiltonian.terms[l_term]
    prefactor = P[0]
    paulis = P[1]
    qubits = P[2]

    arrays = []
    for i in range(hamiltonian.n_qubits):
        if i in qubits:
            ind_i = qubits.index(i)
            mat = np.sign(prefactor) * qu.pauli(paulis[ind_i])
        else:
            mat = qu.identity(2)
        if (i == 0) or (i == (hamiltonian.n_qubits - 1)):
            aux = np.zeros([1, 2, 2], dtype=complex)
            aux[0, :, :] = mat
        else:
            aux = np.zeros([1, 1, 2, 2], dtype=complex)
            aux[0, 0, :, :] = mat
        arrays.append(aux)

    return qtn.MatrixProductOperator(arrays, shape="lrud")


def _build_llxHl_mpo(hamiltonian, l_term):
    r"""
    Construct the MPO for :math:`\ket{\ell}\bra{\ell} \otimes H_\ell` used in the SELECT oracle.
    """
    m_L = int(np.ceil(np.log2(len(hamiltonian.terms))))
    l_mps = qtn.MPS_computational_state(f"{{0:0{m_L}b}}".format(l_term))
    l_mpo = l_mps.partial_trace_to_mpo(keep=list(range(m_L)))

    Hl_mpo = _build_Hl_mpo(hamiltonian, l_term)

    return kron_mpos(l_mpo, Hl_mpo)


def build_lcu_select_mpo(hamiltonian, *, cutoff=1e-10):
    r"""
    Construct the MPO implementing the SELECT oracle.

    .. math::
        SELECT = \sum_\ell \ket{\ell}\bra{\ell} \otimes H_\ell
    """
    L = len(hamiltonian.terms)
    m_L = int(np.ceil(np.log2(L)))

    select_mpo = _build_llxHl_mpo(hamiltonian, 0)
    for l_term in range(1, 2**m_L):
        aux = _build_llxHl_mpo(hamiltonian, l_term)
        select_mpo = aux + select_mpo
        select_mpo.compress(cutoff=cutoff)

    return select_mpo


###############################################################################
############### WALK operator #################################################
###############################################################################


def build_lcu_reflection_mpo(hamiltonian, *, cutoff=1e-10):
    r"""
    Construct the reflection operator :math:`\mathcal{R}_L` for the L register.

    .. math::
        \mathcal{R}_L = 2 \ket{\mathcal{L}}\bra{\mathcal{L}}\otimes\mathbb{1} - \mathbb{1}
    """
    L_mps = build_lcu_prepare_state_mps(hamiltonian)
    m_L = L_mps.L
    L_mpo = L_mps.partial_trace_to_mpo(keep=list(range(m_L)))
    L_mpo.compress(cutoff=cutoff)

    n_qb = hamiltonian.n_qubits
    R_L = 2 * kron_mpos(L_mpo, qtn.MPO_identity(n_qb)) - qtn.MPO_identity(m_L + n_qb)
    R_L.compress(cutoff=cutoff)

    return R_L


###############################################################################
############## QPE ############################################################
###############################################################################


def get_energy_from_lcu_walk_phase(theta, lmb):
    r"""
    Get the energy from the eigenphase of the LCU Walk operator.

    .. math::
        E = \lambda \cos(2 \pi \theta)

    Parameters
    ----------
    theta : float
        Eigenphase of the Walk operator.
    lmb : float
        One-norm of LCU weights.

    Returns
    -------
    energy : float
        Estimated energy.
    """
    return lmb * np.cos(2 * np.pi * theta)


def estimate_lcu_error(m_ph, E0, lmb):
    """
    Estimate the error bound in energy in LCU QPE from finite number of phase qubits.

    Parameters
    ----------
    m_ph : int
        Number of phase estimation qubits.
    E0 : float
        Ground state energy estimate.
    lmb : float
        LCU normalization factor.

    Returns
    -------
    delta_E : float
        Estimated upper bound on the energy error.
    """
    return lmb * np.sqrt(1 - (E0 / lmb) ** 2) * 2 * np.pi / 2**m_ph
