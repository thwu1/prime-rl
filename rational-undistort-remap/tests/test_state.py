"""
Verify the agent's undistort-rectify pipeline against OpenCV reference.
Tests: output files, no-cv2, map accuracy, image accuracy, montage, video output.
"""
import glob
import os
import subprocess
import xml.etree.ElementTree as ET

import cv2
import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_opencv_matrix(elem):
    """Parse an OpenCV FileStorage XML matrix element."""
    rows = int(elem.find('rows').text)
    cols = int(elem.find('cols').text)
    data = list(map(float, elem.find('data').text.split()))
    return np.array(data, dtype=np.float64).reshape(rows, cols)


def _load_calibration():
    """Load calibration from the OpenCV FileStorage XML file."""
    tree = ET.parse('/app/calibration.xml')
    root = tree.getroot()
    K = _parse_opencv_matrix(root.find('camera_matrix'))
    dist = _parse_opencv_matrix(root.find('dist_coeffs'))
    R = _parse_opencv_matrix(root.find('rectification_rotation'))
    K_new = _parse_opencv_matrix(root.find('new_camera_matrix'))
    target_frame = int(root.find('target_frame').text)
    return K, dist, R, K_new, target_frame


def _get_video_info(path):
    """Get video width, height, frame count using ffprobe."""
    result = subprocess.run(
        ['ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v:0',
         '-show_entries', 'stream=width,height,nb_read_frames',
         '-of', 'csv=p=0', path],
        capture_output=True, text=True, check=True
    )
    parts = result.stdout.strip().split(',')
    return int(parts[0]), int(parts[1]), int(parts[2])


def _extract_frame(video_path, frame_idx, output_path):
    """Extract a single 0-indexed frame from a video."""
    subprocess.run([
        'ffmpeg', '-y', '-i', video_path,
        '-vf', f'select=eq(n\\,{frame_idx})',
        '-vsync', 'vfr', '-vframes', '1',
        output_path
    ], check=True, capture_output=True)


# Module-level cache so reference is computed only once.
_REF = {}


def _get_reference():
    if _REF:
        return _REF

    K, dist, R, K_new, target_frame = _load_calibration()
    w, h, num_frames = _get_video_info('/app/input.mkv')

    # Extract target frame independently
    os.makedirs('/tmp/test_ref', exist_ok=True)
    _extract_frame('/app/input.mkv', target_frame, '/tmp/test_ref/frame.png')

    map_x, map_y = cv2.initUndistortRectifyMap(
        K, dist, R, K_new, (w, h), cv2.CV_32FC1
    )

    frame = cv2.imread('/tmp/test_ref/frame.png')
    ref_img = cv2.remap(
        frame, map_x, map_y, cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT, borderValue=0
    )

    _REF.update({
        'K': K, 'dist': dist, 'R': R, 'K_new': K_new,
        'target_frame': target_frame,
        'w': w, 'h': h, 'num_frames': num_frames,
        'map_x': map_x, 'map_y': map_y,
        'frame': frame, 'ref_img': ref_img,
    })
    return _REF


# ---------------------------------------------------------------------------
# Tests — output files exist
# ---------------------------------------------------------------------------

class TestOutputFiles:
    def test_frame_exists(self):
        assert os.path.isfile("/app/frame_02.png"), \
            "Extracted frame not found at /app/frame_02.png"

    def test_undistorted_exists(self):
        assert os.path.isfile("/app/undistorted_02.png"), \
            "Undistorted frame not found at /app/undistorted_02.png"

    def test_map_x_exists(self):
        assert os.path.isfile("/app/map_x.npy"), \
            "map_x.npy not found at /app/map_x.npy"

    def test_map_y_exists(self):
        assert os.path.isfile("/app/map_y.npy"), \
            "map_y.npy not found at /app/map_y.npy"

    def test_montage_exists(self):
        assert os.path.isfile("/app/montage.png"), \
            "Montage not found at /app/montage.png"

    def test_video_exists(self):
        assert os.path.isfile("/app/undistorted_seq.mkv"), \
            "Output video not found at /app/undistorted_seq.mkv"


# ---------------------------------------------------------------------------
# Tests — no OpenCV in the agent's solution code
# ---------------------------------------------------------------------------

class TestNoOpenCV:
    def test_no_cv2_imports_in_app(self):
        """Agent's Python files in /app must not import cv2."""
        for fpath in glob.glob("/app/**/*.py", recursive=True):
            with open(fpath) as f:
                content = f.read()
            assert "import cv2" not in content, \
                f"cv2 import detected in {fpath}"
            assert "from cv2" not in content, \
                f"cv2 import detected in {fpath}"


# ---------------------------------------------------------------------------
# Tests — map coordinate accuracy
# ---------------------------------------------------------------------------

class TestMapAccuracy:
    def test_map_x_shape(self):
        ref = _get_reference()
        mx = np.load("/app/map_x.npy")
        expected = (ref['h'], ref['w'])
        assert mx.shape == expected, \
            f"map_x shape {mx.shape} != {expected}"

    def test_map_y_shape(self):
        ref = _get_reference()
        my = np.load("/app/map_y.npy")
        expected = (ref['h'], ref['w'])
        assert my.shape == expected, \
            f"map_y shape {my.shape} != {expected}"

    def test_map_x_values(self):
        ref = _get_reference()
        agent_x = np.load("/app/map_x.npy").astype(np.float64)
        max_err = np.abs(agent_x - ref['map_x'].astype(np.float64)).max()
        assert max_err < 0.01, \
            f"map_x max error {max_err:.6f} >= 0.01"

    def test_map_y_values(self):
        ref = _get_reference()
        agent_y = np.load("/app/map_y.npy").astype(np.float64)
        max_err = np.abs(agent_y - ref['map_y'].astype(np.float64)).max()
        assert max_err < 0.01, \
            f"map_y max error {max_err:.6f} >= 0.01"


# ---------------------------------------------------------------------------
# Tests — undistorted frame accuracy
# ---------------------------------------------------------------------------

class TestUndistortedFrame:
    def test_output_shape(self):
        ref = _get_reference()
        out = cv2.imread("/app/undistorted_02.png")
        assert out is not None, "Could not load /app/undistorted_02.png"
        assert out.shape == ref['frame'].shape, \
            f"Output shape {out.shape} != input shape {ref['frame'].shape}"

    def test_max_pixel_error(self):
        ref = _get_reference()
        out = cv2.imread("/app/undistorted_02.png")
        assert out is not None
        diff = np.abs(out.astype(np.float64) - ref['ref_img'].astype(np.float64))
        assert diff.max() < 8.0, \
            f"Max pixel error {diff.max()} >= 8.0"

    def test_mean_pixel_error(self):
        ref = _get_reference()
        out = cv2.imread("/app/undistorted_02.png")
        assert out is not None
        diff = np.abs(out.astype(np.float64) - ref['ref_img'].astype(np.float64))
        assert diff.mean() < 1.5, \
            f"Mean pixel error {diff.mean():.4f} >= 1.5"


# ---------------------------------------------------------------------------
# Tests — montage composition
# ---------------------------------------------------------------------------

class TestMontage:
    def test_montage_dimensions(self):
        """Montage must be exactly 2W × H (side-by-side, no padding)."""
        ref = _get_reference()
        montage = cv2.imread("/app/montage.png")
        assert montage is not None, "Could not load /app/montage.png"
        expected = (ref['h'], 2 * ref['w'], 3)
        assert montage.shape == expected, \
            f"Montage shape {montage.shape} != {expected}"

    def test_montage_left_half_matches_original(self):
        """Left half of montage should be the original (distorted) frame."""
        ref = _get_reference()
        montage = cv2.imread("/app/montage.png")
        assert montage is not None
        left = montage[:, :ref['w'], :]
        diff = np.abs(left.astype(np.float64) - ref['frame'].astype(np.float64))
        assert diff.max() < 5.0, \
            f"Montage left half max diff {diff.max()} >= 5.0"

    def test_montage_right_half_matches_undistorted(self):
        """Right half of montage should be the undistorted frame."""
        ref = _get_reference()
        montage = cv2.imread("/app/montage.png")
        assert montage is not None
        right = montage[:, ref['w']:, :]
        diff = np.abs(right.astype(np.float64) - ref['ref_img'].astype(np.float64))
        assert diff.max() < 10.0, \
            f"Montage right half max diff {diff.max()} >= 10.0"


# ---------------------------------------------------------------------------
# Tests — lossless video output
# ---------------------------------------------------------------------------

class TestVideoOutput:
    def test_frame_count(self):
        """Output video must have the same number of frames as input."""
        ref = _get_reference()
        _, _, n = _get_video_info('/app/undistorted_seq.mkv')
        assert n == ref['num_frames'], \
            f"Output video has {n} frames, expected {ref['num_frames']}"

    def test_frame_accuracy(self):
        """Each frame in the output video must match the OpenCV reference."""
        ref = _get_reference()

        os.makedirs('/tmp/test_seq_out', exist_ok=True)
        subprocess.run([
            'ffmpeg', '-y', '-i', '/app/undistorted_seq.mkv',
            '/tmp/test_seq_out/frame_%03d.png'
        ], check=True, capture_output=True)

        os.makedirs('/tmp/test_seq_in', exist_ok=True)
        subprocess.run([
            'ffmpeg', '-y', '-i', '/app/input.mkv',
            '/tmp/test_seq_in/frame_%03d.png'
        ], check=True, capture_output=True)

        for i in range(ref['num_frames']):
            in_frame = cv2.imread(f'/tmp/test_seq_in/frame_{i+1:03d}.png')
            out_frame = cv2.imread(f'/tmp/test_seq_out/frame_{i+1:03d}.png')
            assert out_frame is not None, \
                f"Missing frame {i+1} in output video"

            ref_frame = cv2.remap(
                in_frame, ref['map_x'], ref['map_y'],
                cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_CONSTANT, borderValue=0
            )
            diff = np.abs(
                out_frame.astype(np.float64) - ref_frame.astype(np.float64)
            )
            assert diff.max() < 10.0, \
                f"Frame {i+1}: max pixel error {diff.max()} >= 10.0"
            assert diff.mean() < 3.0, \
                f"Frame {i+1}: mean pixel error {diff.mean():.4f} >= 3.0"
