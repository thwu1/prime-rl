
import subprocess
import os
import shutil
import pytest

BUILD_DIR = "/app/build"
TEST_BINARY = os.path.join(BUILD_DIR, "test_runner")


@pytest.fixture(scope="session")
def build_test_binary():
    """Build the project using CMake."""
    if os.path.exists(BUILD_DIR):
        shutil.rmtree(BUILD_DIR)
    os.makedirs(BUILD_DIR)

    cmake_result = subprocess.run(
        ["cmake", ".."],
        capture_output=True, text=True, timeout=60,
        cwd=BUILD_DIR
    )
    assert cmake_result.returncode == 0, (
        f"CMake configuration failed:\n{cmake_result.stdout}\n{cmake_result.stderr}"
    )

    build_result = subprocess.run(
        ["cmake", "--build", "."],
        capture_output=True, text=True, timeout=120,
        cwd=BUILD_DIR
    )
    assert build_result.returncode == 0, (
        f"Build failed:\n{build_result.stdout}\n{build_result.stderr}"
    )

    assert os.path.exists(TEST_BINARY), "Test binary was not created"
    return TEST_BINARY


@pytest.fixture(scope="session")
def test_output(build_test_binary):
    """Run the test binary and capture output."""
    result = subprocess.run(
        [build_test_binary], capture_output=True, text=True, timeout=120
    )
    return result


def parse_test_results(output):
    """Parse test results from the C++ test runner output."""
    results = {}
    for line in output.split("\n"):
        line = line.strip()
        if line.startswith("TEST "):
            parts = line.split(" ", 3)
            if len(parts) >= 3:
                name = parts[1]
                status = parts[2]
                results[name] = status == "PASS"
    return results


@pytest.fixture(scope="session")
def parsed_results(test_output):
    return parse_test_results(test_output.stdout)


def test_compilation_succeeds(build_test_binary):
    """The library must compile without errors."""
    assert os.path.exists(build_test_binary)


def test_all_tests_pass(test_output, parsed_results):
    """All C++ tests must pass."""
    failed = [name for name, passed in parsed_results.items() if not passed]
    assert test_output.returncode == 0, (
        f"Test runner exited with code {test_output.returncode}. "
        f"Failed tests: {failed}\n"
        f"Full output:\n{test_output.stdout}"
    )


def test_set_euler_all_orders(parsed_results):
    """set_euler must work for all 6 Euler orders."""
    for order in ["XYZ", "XZY", "YXZ", "YZX", "ZXY", "ZYX"]:
        key = f"set_euler_nontrivial_{order}"
        assert key in parsed_results, f"Missing test: {key}"
        assert parsed_results[key], f"set_euler failed for order {order}"


def test_euler_cross_roundtrip_all_orders(parsed_results):
    """Euler cross-order roundtrip must pass for all orders."""
    for order in ["XYZ", "XZY", "YXZ", "YZX", "ZXY", "ZYX"]:
        key = f"euler_cross_roundtrip_{order}"
        assert key in parsed_results, f"Missing test: {key}"
        assert parsed_results[key], f"Cross-order roundtrip failed for {order}"


def test_euler_self_roundtrip_all_orders(parsed_results):
    """Euler self-roundtrip must pass for all orders."""
    for order in ["XYZ", "XZY", "YXZ", "YZX", "ZXY", "ZYX"]:
        key = f"euler_self_roundtrip_{order}"
        assert key in parsed_results, f"Missing test: {key}"
        assert parsed_results[key], f"Self-roundtrip failed for {order}"


def test_quaternion_roundtrip(parsed_results):
    """Matrix -> Quaternion -> Matrix roundtrip must be correct."""
    assert parsed_results.get("quaternion_from_matrix_roundtrip", False), \
        "Quaternion from matrix roundtrip failed"


def test_axis_angle_180(parsed_results):
    """Axis-angle extraction at 180 degrees must work."""
    assert parsed_results.get("axis_angle_180_y", False), \
        "180-degree axis-angle extraction failed"


def test_slerp_antipodal(parsed_results):
    """Slerp must handle antipodal quaternions correctly."""
    assert parsed_results.get("slerp_antipodal_same_rotation", False), \
        "Slerp antipodal correction failed"


def test_conformal_partial_uniform(parsed_results):
    """is_conformal must reject partial uniform scale."""
    assert parsed_results.get("partial_uniform_not_conformal", False), \
        "is_conformal incorrectly accepts partial uniform scale"


def test_quat_xform_consistency(parsed_results):
    """Quaternion xform must match matrix xform."""
    assert parsed_results.get("quat_xform_matches_matrix", False), \
        "Quaternion xform doesn't match matrix xform"


def test_log_rotation_basic(parsed_results):
    """log_rotation must return correct rotation vectors."""
    assert parsed_results.get("log_rotation_identity", False), \
        "log_rotation failed for identity"
    assert parsed_results.get("log_rotation_90_z", False), \
        "log_rotation failed for 90-degree rotation about Z"
    assert parsed_results.get("log_rotation_no_nan", False), \
        "log_rotation produced NaN"


def test_log_rotation_singularities(parsed_results):
    """log_rotation must handle 180-degree and small-angle cases."""
    assert parsed_results.get("log_rotation_180", False), \
        "log_rotation failed for 180-degree rotation"
    assert parsed_results.get("log_rotation_small_angle", False), \
        "log_rotation failed for small angle"
    assert parsed_results.get("log_rotation_roundtrip", False), \
        "log_rotation roundtrip failed"


def test_geodesic_distance_basic(parsed_results):
    """Geodesic distance must compute correct distances."""
    assert parsed_results.get("geodesic_distance_self_zero", False), \
        "geodesic_distance not zero for identical rotations"
    assert parsed_results.get("geodesic_distance_90", False), \
        "geodesic_distance wrong for 90-degree separation"
    assert parsed_results.get("geodesic_distance_180", False), \
        "geodesic_distance wrong for 180-degree separation"


def test_geodesic_distance_properties(parsed_results):
    """Geodesic distance must satisfy metric properties."""
    assert parsed_results.get("geodesic_distance_symmetric", False), \
        "geodesic_distance is not symmetric"
    assert parsed_results.get("geodesic_distance_nonneg", False), \
        "geodesic_distance is negative"
    assert parsed_results.get("geodesic_distance_triangle_ineq", False), \
        "geodesic_distance violates triangle inequality"


def test_swing_twist_composition(parsed_results):
    """swing * twist must reconstruct the original rotation."""
    assert parsed_results.get("swing_twist_composition", False), \
        "swing_twist decomposition failed composition check"
    assert parsed_results.get("swing_twist_z_axis_composition", False), \
        "swing_twist composition failed for Z axis"


def test_swing_twist_pure_cases(parsed_results):
    """Swing-twist must handle pure twist and pure swing correctly."""
    assert parsed_results.get("swing_twist_pure_twist_swing_id", False), \
        "Pure twist should produce identity swing"
    assert parsed_results.get("swing_twist_pure_swing_twist_id", False), \
        "Pure swing should produce identity twist"


def test_swing_twist_geometric_properties(parsed_results):
    """Swing-twist components must have correct geometric properties."""
    assert parsed_results.get("swing_twist_normalized", False), \
        "swing_twist outputs are not normalized"
    assert parsed_results.get("swing_twist_axis_parallel", False), \
        "twist axis not parallel to given axis"
    assert parsed_results.get("swing_twist_swing_perp", False), \
        "swing not perpendicular to twist axis"
