
import subprocess
import json
import math
import os
import shutil
import sqlite3
import ctypes
import numpy as np
import pytest

def run_tool(input_data):
    """Run rotations.py with JSON input, return parsed JSON output."""
    proc = subprocess.run(
        ["python3", "/app/rotations.py"],
        input=json.dumps(input_data),
        capture_output=True, text=True, timeout=30
    )
    assert proc.returncode == 0, f"Process failed: {proc.stderr}"
    return json.loads(proc.stdout)

def rot_x(a):
    return np.array([[1,0,0],[0,math.cos(a),-math.sin(a)],[0,math.sin(a),math.cos(a)]])

def rot_y(a):
    return np.array([[math.cos(a),0,math.sin(a)],[0,1,0],[-math.sin(a),0,math.cos(a)]])

def rot_z(a):
    return np.array([[math.cos(a),-math.sin(a),0],[math.sin(a),math.cos(a),0],[0,0,1]])

ROT_FUNC = {'X': rot_x, 'Y': rot_y, 'Z': rot_z}

CARDAN_SEQS = ['XYZ', 'XZY', 'YXZ', 'YZX', 'ZXY', 'ZYX']
EULER_SEQS = ['XYX', 'XZX', 'YXY', 'YZY', 'ZXZ', 'ZYZ']
ALL_SEQS = CARDAN_SEQS + EULER_SEQS

def build_matrix(angles, seq):
    R = ROT_FUNC[seq[0]](angles[0]) @ ROT_FUNC[seq[1]](angles[1]) @ ROT_FUNC[seq[2]](angles[2])
    return R

def mat_to_list(R):
    return [list(row) for row in R.tolist()]


# ========== C LIBRARY TESTS ==========

class TestCLibrary:
    """Verify the C shared library exists, exports correct symbols, and produces correct results."""

    def test_so_exists(self):
        """librotcore.so must exist at /app/librotcore.so."""
        assert os.path.isfile('/app/librotcore.so'), "C shared library not found at /app/librotcore.so"

    def test_so_loadable(self):
        """librotcore.so must be loadable as a shared library."""
        lib = ctypes.CDLL('/app/librotcore.so')
        assert lib is not None

    def test_compose_symbol_exists(self):
        """rotcore_compose must be an exported symbol."""
        lib = ctypes.CDLL('/app/librotcore.so')
        fn = getattr(lib, 'rotcore_compose', None)
        assert fn is not None, "rotcore_compose not found in librotcore.so"

    def test_decompose_symbol_exists(self):
        """rotcore_decompose must be an exported symbol."""
        lib = ctypes.CDLL('/app/librotcore.so')
        fn = getattr(lib, 'rotcore_decompose', None)
        assert fn is not None, "rotcore_decompose not found in librotcore.so"

    def test_mat_to_quat_symbol_exists(self):
        """rotcore_mat_to_quat must be an exported symbol."""
        lib = ctypes.CDLL('/app/librotcore.so')
        fn = getattr(lib, 'rotcore_mat_to_quat', None)
        assert fn is not None, "rotcore_mat_to_quat not found in librotcore.so"

    def test_direct_compose_xyz(self):
        """Call rotcore_compose directly and verify result."""
        lib = ctypes.CDLL('/app/librotcore.so')
        lib.rotcore_compose.argtypes = [
            ctypes.POINTER(ctypes.c_double), ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_double)
        ]
        lib.rotcore_compose.restype = None

        angles = (ctypes.c_double * 3)(0.3, 0.5, -0.2)
        R_out = (ctypes.c_double * 9)()
        lib.rotcore_compose(angles, b'XYZ', R_out)

        expected = build_matrix([0.3, 0.5, -0.2], 'XYZ')
        for i in range(3):
            for j in range(3):
                assert abs(R_out[i*3+j] - expected[i][j]) < 1e-10, \
                    f"C compose mismatch at [{i}][{j}]: got {R_out[i*3+j]}, expected {expected[i][j]}"

    @pytest.mark.parametrize("seq", ['ZXY', 'YZY', 'XZX'])
    def test_direct_compose_various(self, seq):
        """Call rotcore_compose for various sequences and verify."""
        lib = ctypes.CDLL('/app/librotcore.so')
        lib.rotcore_compose.argtypes = [
            ctypes.POINTER(ctypes.c_double), ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_double)
        ]
        lib.rotcore_compose.restype = None

        angles_in = [0.7, 0.4, -0.6]
        angles = (ctypes.c_double * 3)(*angles_in)
        R_out = (ctypes.c_double * 9)()
        lib.rotcore_compose(angles, seq.encode(), R_out)

        expected = build_matrix(angles_in, seq)
        for i in range(3):
            for j in range(3):
                assert abs(R_out[i*3+j] - expected[i][j]) < 1e-10

    def test_direct_decompose_roundtrip(self):
        """Call rotcore_compose then rotcore_decompose, verify round-trip."""
        lib = ctypes.CDLL('/app/librotcore.so')
        lib.rotcore_compose.argtypes = [
            ctypes.POINTER(ctypes.c_double), ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_double)
        ]
        lib.rotcore_compose.restype = None
        lib.rotcore_decompose.argtypes = [
            ctypes.POINTER(ctypes.c_double), ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_double)
        ]
        lib.rotcore_decompose.restype = ctypes.c_int

        angles_in = (ctypes.c_double * 3)(0.3, 0.5, -0.2)
        R = (ctypes.c_double * 9)()
        lib.rotcore_compose(angles_in, b'XYZ', R)

        angles_out = (ctypes.c_double * 3)()
        ret = lib.rotcore_decompose(R, b'XYZ', angles_out)

        # Recompose and verify
        R2 = (ctypes.c_double * 9)()
        lib.rotcore_compose(angles_out, b'XYZ', R2)

        for i in range(9):
            assert abs(R[i] - R2[i]) < 1e-10, \
                f"C decompose round-trip failed at index {i}"

    def test_direct_mat_to_quat_identity(self):
        """rotcore_mat_to_quat on identity -> [1,0,0,0]."""
        lib = ctypes.CDLL('/app/librotcore.so')
        lib.rotcore_mat_to_quat.argtypes = [
            ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double)
        ]
        lib.rotcore_mat_to_quat.restype = None

        R = (ctypes.c_double * 9)(1,0,0, 0,1,0, 0,0,1)
        q = (ctypes.c_double * 4)()
        lib.rotcore_mat_to_quat(R, q)

        np.testing.assert_allclose([q[0], q[1], q[2], q[3]], [1.0, 0.0, 0.0, 0.0], atol=1e-10)

    def test_direct_mat_to_quat_near180(self):
        """rotcore_mat_to_quat near 180 degrees must be stable."""
        lib = ctypes.CDLL('/app/librotcore.so')
        lib.rotcore_mat_to_quat.argtypes = [
            ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double)
        ]
        lib.rotcore_mat_to_quat.restype = None

        angle = 179 * math.pi / 180
        R_np = rot_y(angle)
        R = (ctypes.c_double * 9)(*R_np.flatten().tolist())
        q = (ctypes.c_double * 4)()
        lib.rotcore_mat_to_quat(R, q)

        q_norm = math.sqrt(sum(q[i]**2 for i in range(4)))
        assert abs(q_norm - 1.0) < 1e-10, f"Quaternion not unit norm: {q_norm}"
        assert q[0] >= -1e-10, f"w should be >= 0, got {q[0]}"


# ========== CLI-C INTEGRATION TESTS ==========

class TestCLIIntegration:
    """Verify the Python CLI actually uses the C shared library."""

    def test_cli_fails_without_so(self):
        """CLI must fail when librotcore.so is removed, proving it's actually used."""
        so_path = '/app/librotcore.so'
        backup = '/app/librotcore.so.test_bak'
        if not os.path.isfile(so_path):
            pytest.skip("librotcore.so not found")

        shutil.move(so_path, backup)
        try:
            proc = subprocess.run(
                ["python3", "/app/rotations.py"],
                input=json.dumps({"command": "compose", "angles": [0.1, 0.2, 0.3], "sequence": "XYZ"}),
                capture_output=True, text=True, timeout=10
            )
            assert proc.returncode != 0, \
                "CLI should fail without C library — it may not actually use librotcore.so"
        finally:
            shutil.move(backup, so_path)

    def test_cli_compose_matches_c(self):
        """CLI compose output must match direct C library call."""
        lib = ctypes.CDLL('/app/librotcore.so')
        lib.rotcore_compose.argtypes = [
            ctypes.POINTER(ctypes.c_double), ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_double)
        ]
        lib.rotcore_compose.restype = None

        angles_in = [1.2, -0.4, 0.8]
        c_angles = (ctypes.c_double * 3)(*angles_in)
        c_R = (ctypes.c_double * 9)()
        lib.rotcore_compose(c_angles, b'ZYX', c_R)

        cli_result = run_tool({"command": "compose", "angles": angles_in, "sequence": "ZYX"})
        cli_R = cli_result["matrix"]

        for i in range(3):
            for j in range(3):
                assert abs(c_R[i*3+j] - cli_R[i][j]) < 1e-14, \
                    f"CLI/C mismatch at [{i}][{j}]"


# ========== COMPOSE TESTS ==========

class TestCompose:
    @pytest.mark.parametrize("seq", ALL_SEQS)
    def test_compose_identity(self, seq):
        """Composing [0,0,0] should give identity matrix."""
        result = run_tool({"command": "compose", "angles": [0.0, 0.0, 0.0], "sequence": seq})
        R = np.array(result["matrix"])
        np.testing.assert_allclose(R, np.eye(3), atol=1e-10)

    @pytest.mark.parametrize("seq", ALL_SEQS)
    def test_compose_known_angles(self, seq):
        """Composing known angles should match reference matrix."""
        angles = [0.3, 0.5, -0.2]
        expected = build_matrix(angles, seq)
        result = run_tool({"command": "compose", "angles": angles, "sequence": seq})
        R = np.array(result["matrix"])
        np.testing.assert_allclose(R, expected, atol=1e-10)

    def test_compose_90_degree_xyz(self):
        """XYZ compose with 90-degree Y rotation."""
        angles = [0.0, math.pi / 2, 0.0]
        expected = build_matrix(angles, 'XYZ')
        result = run_tool({"command": "compose", "angles": angles, "sequence": "XYZ"})
        R = np.array(result["matrix"])
        np.testing.assert_allclose(R, expected, atol=1e-10)


# ========== DECOMPOSE TESTS ==========

class TestDecompose:
    @pytest.mark.parametrize("seq", CARDAN_SEQS)
    def test_decompose_roundtrip_cardan(self, seq):
        """Decompose a matrix built from known Cardan angles, verify round-trip."""
        angles_in = [0.7, 0.4, -0.6]
        R = build_matrix(angles_in, seq)
        result = run_tool({"command": "decompose", "matrix": mat_to_list(R), "sequence": seq})
        angles_out = result["angles"]
        R2 = build_matrix(angles_out, seq)
        np.testing.assert_allclose(R2, R, atol=1e-10)

    @pytest.mark.parametrize("seq", EULER_SEQS)
    def test_decompose_roundtrip_euler(self, seq):
        """Decompose a matrix built from known proper-Euler angles, verify round-trip."""
        angles_in = [1.2, 0.8, -0.5]
        R = build_matrix(angles_in, seq)
        result = run_tool({"command": "decompose", "matrix": mat_to_list(R), "sequence": seq})
        angles_out = result["angles"]
        R2 = build_matrix(angles_out, seq)
        np.testing.assert_allclose(R2, R, atol=1e-10)

    def test_decompose_identity_xyz(self):
        """Identity matrix should decompose to [0,0,0] for XYZ."""
        result = run_tool({"command": "decompose", "matrix": mat_to_list(np.eye(3)), "sequence": "XYZ"})
        np.testing.assert_allclose(result["angles"], [0.0, 0.0, 0.0], atol=1e-10)

    @pytest.mark.parametrize("seq", CARDAN_SEQS)
    def test_decompose_near_gimbal_cardan(self, seq):
        """Test decomposition near gimbal lock (beta ~ pi/2) still produces valid matrix."""
        angles_in = [0.3, math.pi/2 - 1e-8, -0.7]
        R = build_matrix(angles_in, seq)
        result = run_tool({"command": "decompose", "matrix": mat_to_list(R), "sequence": seq})
        R2 = build_matrix(result["angles"], seq)
        np.testing.assert_allclose(R2, R, atol=1e-6)

    @pytest.mark.parametrize("seq", EULER_SEQS)
    def test_decompose_near_gimbal_euler(self, seq):
        """Test decomposition near gimbal lock (beta ~ 0) for proper-Euler."""
        angles_in = [0.5, 1e-8, -0.3]
        R = build_matrix(angles_in, seq)
        result = run_tool({"command": "decompose", "matrix": mat_to_list(R), "sequence": seq})
        R2 = build_matrix(result["angles"], seq)
        np.testing.assert_allclose(R2, R, atol=1e-6)

    def test_decompose_large_angles(self):
        """Test with angles exceeding pi, verify matrix equivalence."""
        angles_in = [2.5, 0.3, -2.8]
        R = build_matrix(angles_in, 'ZYX')
        result = run_tool({"command": "decompose", "matrix": mat_to_list(R), "sequence": "ZYX"})
        R2 = build_matrix(result["angles"], 'ZYX')
        np.testing.assert_allclose(R2, R, atol=1e-10)

    def test_decompose_multiple_sequences_same_matrix(self):
        """Same rotation matrix decomposed with different sequences should recompose to same matrix."""
        R = build_matrix([0.5, 0.3, -0.4], 'XYZ')
        for seq in ALL_SEQS:
            result = run_tool({"command": "decompose", "matrix": mat_to_list(R), "sequence": seq})
            R2 = build_matrix(result["angles"], seq)
            np.testing.assert_allclose(R2, R, atol=1e-10,
                err_msg=f"Failed for sequence {seq}")


# ========== CONTINUOUS ANGLES TESTS ==========

class TestContinuous:
    def test_continuous_smooth_motion(self):
        """Smooth rotation should produce smooth angle output."""
        N = 50
        matrices = []
        for i in range(N):
            t = i * 0.05
            R = build_matrix([0.3 * t, 0.1 * math.sin(t), -0.2 * t], 'XYZ')
            matrices.append(mat_to_list(R))
        result = run_tool({"command": "continuous", "matrices": matrices, "sequence": "XYZ"})
        series = result["angle_series"]
        assert len(series) == N
        for i in range(1, N):
            for j in range(3):
                diff = abs(series[i][j] - series[i-1][j])
                assert diff < 0.5, f"Frame {i}, angle {j}: jump={diff}"

    def test_continuous_through_gimbal_lock(self):
        """Motion passing through gimbal lock should remain continuous."""
        N = 60
        matrices = []
        for i in range(N):
            t = i / (N - 1)
            beta = math.pi * (t - 0.5)
            R = build_matrix([0.3, beta, -0.4], 'XYZ')
            matrices.append(mat_to_list(R))
        result = run_tool({"command": "continuous", "matrices": matrices, "sequence": "XYZ"})
        series = result["angle_series"]
        gimbal = result["gimbal_lock_frames"]
        assert len(gimbal) > 0, "Should detect gimbal lock frames"
        for i, angles in enumerate(series):
            R_ref = np.array(matrices[i])
            R_rec = build_matrix(angles, 'XYZ')
            np.testing.assert_allclose(R_rec, R_ref, atol=1e-6,
                err_msg=f"Frame {i} recomposition failed")

    def test_continuous_wrapping(self):
        """Rotation continuously increasing past pi should not wrap abruptly."""
        N = 80
        matrices = []
        for i in range(N):
            angle = -math.pi + i * (2.5 * math.pi / (N - 1))
            R = build_matrix([angle, 0.1, 0.0], 'ZYX')
            matrices.append(mat_to_list(R))
        result = run_tool({"command": "continuous", "matrices": matrices, "sequence": "ZYX"})
        series = result["angle_series"]
        max_jump = 0
        for i in range(1, N):
            diff = abs(series[i][0] - series[i-1][0])
            max_jump = max(max_jump, diff)
        assert max_jump < 0.5, f"Max jump in continuous angles: {max_jump}"

    def test_gimbal_lock_detection(self):
        """Frames at exact gimbal lock should be reported."""
        matrices = []
        matrices.append(mat_to_list(build_matrix([0.3, 0.5, -0.2], 'XYZ')))
        matrices.append(mat_to_list(build_matrix([0.3, math.pi/2, -0.2], 'XYZ')))
        matrices.append(mat_to_list(build_matrix([0.3, 0.6, -0.2], 'XYZ')))
        result = run_tool({"command": "continuous", "matrices": matrices, "sequence": "XYZ"})
        assert 1 in result["gimbal_lock_frames"]


# ========== ANGULAR VELOCITY TESTS ==========

class TestAngularVelocity:
    def test_constant_rotation_x(self):
        """Constant rotation about X at 1 rad/s should give omega = [1,0,0]."""
        dt = 0.01
        N = 50
        matrices = []
        for i in range(N):
            t = i * dt
            R = rot_x(t)
            matrices.append(mat_to_list(R))
        result = run_tool({"command": "angular_velocity", "matrices": matrices, "dt": dt})
        omega = np.array(result["omega"])
        assert omega.shape == (N, 3)
        for i in range(2, N - 2):
            np.testing.assert_allclose(omega[i], [1.0, 0.0, 0.0], atol=1e-4,
                err_msg=f"Frame {i}")

    def test_constant_rotation_z(self):
        """Constant rotation about Z at 2 rad/s."""
        dt = 0.005
        N = 40
        rate = 2.0
        matrices = [mat_to_list(rot_z(rate * i * dt)) for i in range(N)]
        result = run_tool({"command": "angular_velocity", "matrices": matrices, "dt": dt})
        omega = np.array(result["omega"])
        for i in range(2, N - 2):
            np.testing.assert_allclose(omega[i], [0.0, 0.0, rate], atol=1e-3)

    def test_combined_rotation(self):
        """Rotation about a known fixed axis."""
        dt = 0.01
        N = 30
        axis = np.array([1.0, 1.0, 0.0]) / math.sqrt(2)
        expected_omega = axis * 1.0
        matrices = []
        for i in range(N):
            t = i * dt
            angle = t
            K = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
            R = np.eye(3) + math.sin(angle) * K + (1 - math.cos(angle)) * (K @ K)
            matrices.append(mat_to_list(R))
        result = run_tool({"command": "angular_velocity", "matrices": matrices, "dt": dt})
        omega = np.array(result["omega"])
        for i in range(2, N - 2):
            np.testing.assert_allclose(omega[i], expected_omega, atol=1e-3,
                err_msg=f"Frame {i}")

    def test_stationary(self):
        """No rotation should give zero angular velocity."""
        matrices = [mat_to_list(np.eye(3))] * 10
        result = run_tool({"command": "angular_velocity", "matrices": matrices, "dt": 0.01})
        omega = np.array(result["omega"])
        np.testing.assert_allclose(omega, np.zeros((10, 3)), atol=1e-10)


# ========== CONVERT TESTS ==========

class TestConvert:
    def test_matrix_to_quaternion_identity(self):
        """Identity matrix -> quaternion [1,0,0,0]."""
        result = run_tool({"command": "convert", "from": "matrix", "to": "quaternion",
                          "value": mat_to_list(np.eye(3))})
        q = result["value"]
        np.testing.assert_allclose(q, [1.0, 0.0, 0.0, 0.0], atol=1e-10)

    def test_quaternion_to_matrix_roundtrip(self):
        """Quaternion -> matrix -> quaternion round-trip."""
        q_in = [0.5, 0.5, 0.5, 0.5]
        r1 = run_tool({"command": "convert", "from": "quaternion", "to": "matrix", "value": q_in})
        r2 = run_tool({"command": "convert", "from": "matrix", "to": "quaternion", "value": r1["value"]})
        q_out = r2["value"]
        assert q_out[0] >= 0
        np.testing.assert_allclose(q_out, q_in, atol=1e-10)

    def test_matrix_to_helical_90z(self):
        """90-degree rotation about Z -> helical [0, 0, pi/2]."""
        R = rot_z(math.pi / 2)
        result = run_tool({"command": "convert", "from": "matrix", "to": "helical",
                          "value": mat_to_list(R)})
        h = result["value"]
        np.testing.assert_allclose(h, [0.0, 0.0, math.pi / 2], atol=1e-10)

    def test_helical_to_matrix_roundtrip(self):
        """Helical -> matrix -> helical round-trip."""
        h_in = [0.3, -0.5, 0.7]
        r1 = run_tool({"command": "convert", "from": "helical", "to": "matrix", "value": h_in})
        r2 = run_tool({"command": "convert", "from": "matrix", "to": "helical", "value": r1["value"]})
        h_out = r2["value"]
        np.testing.assert_allclose(h_out, h_in, atol=1e-10)

    def test_euler_to_quaternion(self):
        """Euler XYZ angles -> quaternion -> back to matrix, verify."""
        angles = [0.3, 0.5, -0.2]
        seq = "XYZ"
        euler_val = {"angles": angles, "sequence": seq}
        r1 = run_tool({"command": "convert", "from": "euler", "to": "quaternion", "value": euler_val})
        q = r1["value"]
        r2 = run_tool({"command": "convert", "from": "quaternion", "to": "matrix", "value": q})
        R_from_q = np.array(r2["value"])
        R_direct = build_matrix(angles, seq)
        np.testing.assert_allclose(R_from_q, R_direct, atol=1e-10)

    def test_quaternion_to_euler(self):
        """Quaternion -> euler XYZ -> compose, verify matches quaternion's matrix."""
        q_in = [math.cos(0.3), math.sin(0.3) * 0.0, math.sin(0.3) * 1.0, math.sin(0.3) * 0.0]
        norm = math.sqrt(sum(x**2 for x in q_in))
        q_in = [x / norm for x in q_in]
        r1 = run_tool({"command": "convert", "from": "quaternion", "to": "matrix", "value": q_in})
        R_ref = np.array(r1["value"])
        r2 = run_tool({"command": "convert", "from": "quaternion", "to": "euler",
                       "value": {"quaternion": q_in, "sequence": "XYZ"}})
        euler_out = r2["value"]
        angles = euler_out["angles"]
        R_euler = build_matrix(angles, "XYZ")
        np.testing.assert_allclose(R_euler, R_ref, atol=1e-10)

    def test_helical_to_quaternion(self):
        """Helical -> quaternion consistency."""
        h_in = [0.0, 0.0, math.pi / 3]
        r1 = run_tool({"command": "convert", "from": "helical", "to": "quaternion", "value": h_in})
        q = r1["value"]
        expected_q = [math.cos(math.pi/6), 0.0, 0.0, math.sin(math.pi/6)]
        np.testing.assert_allclose(q, expected_q, atol=1e-10)

    def test_matrix_to_quaternion_shepperd_stability(self):
        """Stability for rotation near 180 degrees."""
        angle = 179 * math.pi / 180
        R = rot_y(angle)
        result = run_tool({"command": "convert", "from": "matrix", "to": "quaternion",
                          "value": mat_to_list(R)})
        q = result["value"]
        q_norm = math.sqrt(sum(x**2 for x in q))
        assert abs(q_norm - 1.0) < 1e-10
        assert q[0] >= -1e-10
        r2 = run_tool({"command": "convert", "from": "quaternion", "to": "matrix", "value": q})
        R2 = np.array(r2["value"])
        np.testing.assert_allclose(R2, R, atol=1e-10)

    def test_all_conversion_paths(self):
        """Build a rotation, convert through all representations, verify consistency."""
        R_orig = build_matrix([0.5, 0.3, -0.4], 'XYZ')
        r1 = run_tool({"command": "convert", "from": "matrix", "to": "quaternion",
                       "value": mat_to_list(R_orig)})
        q = r1["value"]
        r2 = run_tool({"command": "convert", "from": "quaternion", "to": "helical", "value": q})
        h = r2["value"]
        r3 = run_tool({"command": "convert", "from": "helical", "to": "matrix", "value": h})
        R_final = np.array(r3["value"])
        np.testing.assert_allclose(R_final, R_orig, atol=1e-10)

    def test_zero_rotation_helical(self):
        """Zero rotation: matrix identity -> helical [0,0,0]."""
        result = run_tool({"command": "convert", "from": "matrix", "to": "helical",
                          "value": mat_to_list(np.eye(3))})
        np.testing.assert_allclose(result["value"], [0.0, 0.0, 0.0], atol=1e-10)


# ========== BATCH PROCESSING TESTS ==========

class TestBatch:
    def _make_trial_data(self):
        """Create test trial data with known rotation matrices."""
        N = 25
        dt = 0.01
        conventions = {
            "hip": {"sequence": "ZXY"},
            "knee": {"sequence": "ZYX"},
            "ankle": {"sequence": "XYZ"}
        }

        frames = []
        for i in range(N):
            t = i * dt
            frame_joints = {}
            hip_R = build_matrix([0.3*t, 0.1*math.sin(t), -0.2*t], 'ZXY')
            frame_joints["hip"] = mat_to_list(hip_R)
            knee_R = build_matrix([0.5*t, 0.05*t, -0.1*t], 'ZYX')
            frame_joints["knee"] = mat_to_list(knee_R)
            ankle_R = build_matrix([0.1*t, 0.2*math.sin(2*t), -0.15*t], 'XYZ')
            frame_joints["ankle"] = mat_to_list(ankle_R)
            frames.append({"frame": i, "joints": frame_joints})

        trial = {"sampling_rate": 1.0/dt, "frames": frames}
        return trial, conventions, dt

    def _write_trial_files(self, trial, conventions):
        """Write trial and convention files to /app/data/."""
        os.makedirs("/app/data", exist_ok=True)
        trial_path = "/app/data/_test_trial.json"
        conv_path = "/app/data/_test_conventions.json"
        with open(trial_path, 'w') as f:
            json.dump(trial, f)
        with open(conv_path, 'w') as f:
            json.dump(conventions, f)
        return trial_path, conv_path

    def test_batch_output_structure(self):
        """Batch output must contain all joints with required fields."""
        trial, conventions, dt = self._make_trial_data()
        trial_path, conv_path = self._write_trial_files(trial, conventions)
        result = run_tool({
            "command": "batch",
            "trial_file": trial_path,
            "conventions_file": conv_path,
            "dt": dt
        })
        assert "joints" in result
        for joint in ["hip", "knee", "ankle"]:
            assert joint in result["joints"], f"Missing joint: {joint}"
            j = result["joints"][joint]
            assert "sequence" in j
            assert "angles" in j
            assert "angular_velocity" in j
            assert "gimbal_lock_frames" in j
            assert len(j["angles"]) == 25
            assert len(j["angular_velocity"]) == 25
            assert j["sequence"] == conventions[joint]["sequence"]

    def test_batch_angle_accuracy(self):
        """Batch angles must recompose to original matrices."""
        trial, conventions, dt = self._make_trial_data()
        trial_path, conv_path = self._write_trial_files(trial, conventions)
        result = run_tool({
            "command": "batch",
            "trial_file": trial_path,
            "conventions_file": conv_path,
            "dt": dt
        })
        for joint_name in ["hip", "knee", "ankle"]:
            seq = conventions[joint_name]["sequence"]
            j = result["joints"][joint_name]
            for i, angles in enumerate(j["angles"]):
                R_orig = np.array(trial["frames"][i]["joints"][joint_name])
                R_recomp = build_matrix(angles, seq)
                np.testing.assert_allclose(R_recomp, R_orig, atol=1e-6,
                    err_msg=f"{joint_name} frame {i}")

    def test_batch_continuity(self):
        """Batch angle series must be continuous (no large jumps)."""
        trial, conventions, dt = self._make_trial_data()
        trial_path, conv_path = self._write_trial_files(trial, conventions)
        result = run_tool({
            "command": "batch",
            "trial_file": trial_path,
            "conventions_file": conv_path,
            "dt": dt
        })
        for joint_name in ["hip", "knee", "ankle"]:
            angles = result["joints"][joint_name]["angles"]
            for i in range(1, len(angles)):
                for j in range(3):
                    diff = abs(angles[i][j] - angles[i-1][j])
                    assert diff < 0.5, f"{joint_name} frame {i} angle {j}: jump={diff}"

    def test_batch_angular_velocity(self):
        """Batch angular velocity must match standalone computation."""
        trial, conventions, dt = self._make_trial_data()
        trial_path, conv_path = self._write_trial_files(trial, conventions)
        result = run_tool({
            "command": "batch",
            "trial_file": trial_path,
            "conventions_file": conv_path,
            "dt": dt
        })
        hip_matrices = [trial["frames"][i]["joints"]["hip"] for i in range(len(trial["frames"]))]
        av_result = run_tool({
            "command": "angular_velocity",
            "matrices": hip_matrices,
            "dt": dt
        })
        batch_omega = np.array(result["joints"]["hip"]["angular_velocity"])
        direct_omega = np.array(av_result["omega"])
        np.testing.assert_allclose(batch_omega, direct_omega, atol=1e-10,
            err_msg="Batch angular velocity should match standalone computation")

    def test_batch_partial_joints(self):
        """Batch must handle conventions with joints not in trial data."""
        trial = {
            "sampling_rate": 100.0,
            "frames": [
                {"frame": 0, "joints": {"hip": mat_to_list(np.eye(3))}},
                {"frame": 1, "joints": {"hip": mat_to_list(rot_z(0.1))}},
                {"frame": 2, "joints": {"hip": mat_to_list(rot_z(0.2))}}
            ]
        }
        conventions = {
            "hip": {"sequence": "ZXY"},
            "wrist": {"sequence": "XYZ"}
        }
        trial_path, conv_path = self._write_trial_files(trial, conventions)
        result = run_tool({
            "command": "batch",
            "trial_file": trial_path,
            "conventions_file": conv_path,
            "dt": 0.01
        })
        assert "hip" in result["joints"]
        if "wrist" in result["joints"]:
            assert len(result["joints"]["wrist"]["angles"]) == 0


# ========== SQLITE OUTPUT TESTS ==========

class TestSQLiteOutput:
    """Verify batch command writes correct SQLite database."""

    def _make_trial_data(self):
        N = 10
        dt = 0.01
        conventions = {"hip": {"sequence": "ZXY"}, "knee": {"sequence": "XYZ"}}
        frames = []
        for i in range(N):
            t = i * dt
            frame_joints = {
                "hip": mat_to_list(build_matrix([0.3*t, 0.1*t, -0.2*t], 'ZXY')),
                "knee": mat_to_list(build_matrix([0.2*t, 0.05*t, -0.1*t], 'XYZ'))
            }
            frames.append({"frame": i, "joints": frame_joints})
        trial = {"sampling_rate": 1.0/dt, "frames": frames}
        return trial, conventions, dt

    def _write_files(self, trial, conventions):
        os.makedirs("/app/data", exist_ok=True)
        tp = "/app/data/_sqlite_test_trial.json"
        cp = "/app/data/_sqlite_test_conv.json"
        with open(tp, 'w') as f:
            json.dump(trial, f)
        with open(cp, 'w') as f:
            json.dump(conventions, f)
        return tp, cp

    def test_sqlite_db_created(self):
        """Batch must create /app/results.db."""
        trial, conventions, dt = self._make_trial_data()
        tp, cp = self._write_files(trial, conventions)
        run_tool({"command": "batch", "trial_file": tp, "conventions_file": cp, "dt": dt})
        assert os.path.isfile('/app/results.db'), "results.db not created"

    def test_sqlite_tables_exist(self):
        """Database must have joint_angles and angular_velocity tables."""
        trial, conventions, dt = self._make_trial_data()
        tp, cp = self._write_files(trial, conventions)
        run_tool({"command": "batch", "trial_file": tp, "conventions_file": cp, "dt": dt})

        conn = sqlite3.connect('/app/results.db')
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        conn.close()
        assert 'joint_angles' in tables, f"joint_angles table missing. Found: {tables}"
        assert 'angular_velocity' in tables, f"angular_velocity table missing. Found: {tables}"

    def test_sqlite_joint_angles_schema(self):
        """joint_angles table must have correct columns."""
        trial, conventions, dt = self._make_trial_data()
        tp, cp = self._write_files(trial, conventions)
        run_tool({"command": "batch", "trial_file": tp, "conventions_file": cp, "dt": dt})

        conn = sqlite3.connect('/app/results.db')
        cols = conn.execute("PRAGMA table_info(joint_angles)").fetchall()
        col_names = [c[1] for c in cols]
        conn.close()
        for expected in ['joint', 'frame', 'a0', 'a1', 'a2', 'sequence', 'gimbal_locked']:
            assert expected in col_names, f"Column '{expected}' missing from joint_angles"

    def test_sqlite_angular_velocity_schema(self):
        """angular_velocity table must have correct columns."""
        trial, conventions, dt = self._make_trial_data()
        tp, cp = self._write_files(trial, conventions)
        run_tool({"command": "batch", "trial_file": tp, "conventions_file": cp, "dt": dt})

        conn = sqlite3.connect('/app/results.db')
        cols = conn.execute("PRAGMA table_info(angular_velocity)").fetchall()
        col_names = [c[1] for c in cols]
        conn.close()
        for expected in ['joint', 'frame', 'wx', 'wy', 'wz']:
            assert expected in col_names, f"Column '{expected}' missing from angular_velocity"

    def test_sqlite_data_matches_json(self):
        """SQLite data must match JSON output from batch command."""
        trial, conventions, dt = self._make_trial_data()
        tp, cp = self._write_files(trial, conventions)
        result = run_tool({"command": "batch", "trial_file": tp, "conventions_file": cp, "dt": dt})

        conn = sqlite3.connect('/app/results.db')

        for joint in ["hip", "knee"]:
            json_angles = result["joints"][joint]["angles"]
            rows = conn.execute(
                "SELECT frame, a0, a1, a2 FROM joint_angles WHERE joint=? ORDER BY frame",
                (joint,)).fetchall()
            assert len(rows) == len(json_angles), \
                f"Row count mismatch for {joint}: DB={len(rows)}, JSON={len(json_angles)}"
            for row in rows:
                frame_idx = row[0]
                np.testing.assert_allclose(
                    [row[1], row[2], row[3]], json_angles[frame_idx], atol=1e-12,
                    err_msg=f"SQLite/JSON angle mismatch for {joint} frame {frame_idx}")

            json_omega = result["joints"][joint]["angular_velocity"]
            omega_rows = conn.execute(
                "SELECT frame, wx, wy, wz FROM angular_velocity WHERE joint=? ORDER BY frame",
                (joint,)).fetchall()
            assert len(omega_rows) == len(json_omega)
            for row in omega_rows:
                frame_idx = row[0]
                np.testing.assert_allclose(
                    [row[1], row[2], row[3]], json_omega[frame_idx], atol=1e-12,
                    err_msg=f"SQLite/JSON omega mismatch for {joint} frame {frame_idx}")

        conn.close()

    def test_sqlite_primary_key(self):
        """Tables must enforce primary key (joint, frame) uniqueness."""
        trial, conventions, dt = self._make_trial_data()
        tp, cp = self._write_files(trial, conventions)
        # Run batch twice — second run should overwrite, not fail
        run_tool({"command": "batch", "trial_file": tp, "conventions_file": cp, "dt": dt})
        run_tool({"command": "batch", "trial_file": tp, "conventions_file": cp, "dt": dt})

        conn = sqlite3.connect('/app/results.db')
        count = conn.execute("SELECT COUNT(*) FROM joint_angles WHERE joint='hip'").fetchone()[0]
        conn.close()
        assert count == 10, f"Expected 10 rows for hip after re-run, got {count}"
