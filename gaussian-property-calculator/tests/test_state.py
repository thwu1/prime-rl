
import json
import os
import pytest


@pytest.fixture
def results():
    assert os.path.isfile("/app/results.json"), (
        "results.json not found - compute_properties.py may have failed or not been created"
    )
    with open("/app/results.json") as f:
        return json.load(f)


def test_results_file_exists():
    """The solution script must produce /app/results.json."""
    assert os.path.isfile("/app/results.json")


def test_nuclear_repulsion_energy(results):
    """NRE for initial geometry must match Gaussian's reported value."""
    nre = results["initial_nre_hartree"]
    assert isinstance(nre, (int, float))
    # Gaussian reports 8.5805073971 Hartree for the initial geometry
    assert abs(nre - 8.5805073971) < 0.001, f"NRE={nre}, expected ~8.5805"


def test_mulliken_charge_oxygen(results):
    """Oxygen Mulliken charge computed from the Mulliken population matrix."""
    charges = results["mulliken_charges"]
    assert len(charges) == 3, f"Expected 3 charges, got {len(charges)}"
    # Gaussian reports O charge = -0.652191
    assert abs(charges[0] - (-0.652191)) < 0.05, f"O charge={charges[0]}, expected ~-0.652"


def test_mulliken_charge_hydrogen(results):
    """Hydrogen Mulliken charges computed from the Mulliken population matrix."""
    charges = results["mulliken_charges"]
    # Gaussian reports H charges = 0.326096
    assert abs(charges[1] - 0.326096) < 0.05, f"H1 charge={charges[1]}, expected ~0.326"
    assert abs(charges[2] - 0.326096) < 0.05, f"H2 charge={charges[2]}, expected ~0.326"


def test_charge_conservation(results):
    """Mulliken charges must sum to the net charge (0 for neutral water)."""
    charges = results["mulliken_charges"]
    total = sum(charges)
    assert abs(total) < 0.05, f"Sum of charges={total}, expected ~0.0"


def test_total_electrons(results):
    """Sum of Mulliken population matrix must equal total electron count (10 for water)."""
    n_elec = results["total_electrons"]
    assert abs(n_elec - 10.0) < 0.5, f"Total electrons={n_elec}, expected ~10.0"


def test_overlap_trace(results):
    """Overlap trace S[i,i]=Q[i,i]/P[i,i] must sum to nbasis (25)."""
    trace = results["overlap_trace"]
    assert abs(trace - 25.0) < 1.0, f"Overlap trace={trace}, expected ~25.0"


def test_density_reconstruction(results):
    """Reconstructed P from occupied MO coefficients must match parsed P from log."""
    max_err = results["density_matrix_max_error"]
    assert max_err < 0.01, (
        f"Density matrix max element error={max_err}, must be < 0.01"
    )


def test_principal_moments(results):
    """Principal moments of inertia for the final optimized geometry."""
    moments = results["final_principal_moments"]
    assert len(moments) == 3, f"Expected 3 moments, got {len(moments)}"
    # Gaussian thermochemistry section: 2.26084, 4.11372, 6.37456 amu*bohr^2
    ref = [2.26084, 4.11372, 6.37456]
    for i, (m, r) in enumerate(zip(moments, ref)):
        assert abs(m - r) < 0.05, (
            f"Principal moment {i}: {m}, expected ~{r}"
        )


def test_rotational_constants(results):
    """Rotational constants for the final optimized geometry."""
    rcs = results["final_rotational_constants"]
    assert len(rcs) == 3, f"Expected 3 rotational constants, got {len(rcs)}"
    # Gaussian thermochemistry: 798.25963, 438.71295, 283.11609 GHz
    ref = [798.25963, 438.71295, 283.11609]
    for i, (rc, r) in enumerate(zip(rcs, ref)):
        assert abs(rc - r) < 2.0, (
            f"Rotational constant {i}: {rc} GHz, expected ~{r} GHz"
        )


def test_zpve(results):
    """ZPVE computed from harmonic vibrational frequencies."""
    zpve = results["zpve_hartree"]
    # Gaussian reports 0.021667 Hartree/Particle (archive: 0.0216675)
    assert abs(zpve - 0.021667) < 0.001, f"ZPVE={zpve}, expected ~0.021667"


def test_scf_energy(results):
    """Final SCF energy from the archive line."""
    scf = results["final_scf_energy_hartree"]
    # Archive: HF=-76.3406657
    assert abs(scf - (-76.3406657)) < 0.001, (
        f"SCF energy={scf}, expected ~-76.3407"
    )


def test_no_cclib():
    """Solution must not use the cclib library."""
    assert os.path.isfile("/app/compute_properties.py"), (
        "compute_properties.py not found"
    )
    with open("/app/compute_properties.py") as f:
        code = f.read()
    assert "import cclib" not in code and "from cclib" not in code, (
        "Solution must not import cclib"
    )
