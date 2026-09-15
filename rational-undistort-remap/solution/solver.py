#!/usr/bin/env python3
"""
Reference solution for undistort-rectify-pipeline task.

Pipeline: parse OpenCV FileStorage XML → ffprobe → ffmpeg extract →
          NumPy undistortion math → ImageMagick montage → ffmpeg encode.
"""
import os
import subprocess
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image


# ---------------------------------------------------------------------------
# OpenCV FileStorage XML parsing
# ---------------------------------------------------------------------------

def parse_opencv_matrix(elem):
    """Parse an opencv-matrix node from FileStorage XML."""
    rows = int(elem.find('rows').text)
    cols = int(elem.find('cols').text)
    data = list(map(float, elem.find('data').text.split()))
    return np.array(data, dtype=np.float64).reshape(rows, cols)


# ---------------------------------------------------------------------------
# Video inspection / extraction via ffprobe / ffmpeg
# ---------------------------------------------------------------------------

def get_video_info(path):
    """Return (width, height, num_frames) using ffprobe."""
    result = subprocess.run(
        ['ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v:0',
         '-show_entries', 'stream=width,height,nb_read_frames',
         '-of', 'csv=p=0', path],
        capture_output=True, text=True, check=True
    )
    parts = result.stdout.strip().split(',')
    return int(parts[0]), int(parts[1]), int(parts[2])


def extract_frame(video_path, frame_idx, output_path):
    """Extract a single 0-indexed frame from a video with ffmpeg."""
    subprocess.run([
        'ffmpeg', '-y', '-i', video_path,
        '-vf', f'select=eq(n\\,{frame_idx})',
        '-vsync', 'vfr', '-vframes', '1',
        output_path
    ], check=True, capture_output=True)


def extract_all_frames(video_path, output_dir):
    """Extract all frames as PNGs (1-indexed: frame_001.png, ...)."""
    os.makedirs(output_dir, exist_ok=True)
    subprocess.run([
        'ffmpeg', '-y', '-i', video_path,
        os.path.join(output_dir, 'frame_%03d.png')
    ], check=True, capture_output=True)


# ---------------------------------------------------------------------------
# Undistortion math (from-scratch, no OpenCV)
# ---------------------------------------------------------------------------

def compute_maps(K, dist_coeffs, R, K_new, width, height):
    """
    Compute undistortion + rectification coordinate maps.

    Equivalent to cv2.initUndistortRectifyMap(K, dist, R, K_new, (w,h), CV_32FC1).
    """
    k1, k2, p1, p2, k3, k4, k5, k6 = dist_coeffs

    fx, fy = K[0, 0], K[1, 1]
    cx, cy = K[0, 2], K[1, 2]

    iR = np.linalg.inv(K_new @ R)

    jj, ii = np.meshgrid(
        np.arange(width, dtype=np.float64),
        np.arange(height, dtype=np.float64),
    )

    X = iR[0, 0] * jj + iR[0, 1] * ii + iR[0, 2]
    Y = iR[1, 0] * jj + iR[1, 1] * ii + iR[1, 2]
    W = iR[2, 0] * jj + iR[2, 1] * ii + iR[2, 2]

    x = X / W
    y = Y / W

    r2 = x * x + y * y
    r4 = r2 * r2
    r6 = r4 * r2

    kr = (1.0 + k1 * r2 + k2 * r4 + k3 * r6) / \
         (1.0 + k4 * r2 + k5 * r4 + k6 * r6)

    xd = x * kr + 2.0 * p1 * x * y + p2 * (r2 + 2.0 * x * x)
    yd = y * kr + p1 * (r2 + 2.0 * y * y) + 2.0 * p2 * x * y

    map_x = (fx * xd + cx).astype(np.float32)
    map_y = (fy * yd + cy).astype(np.float32)

    return map_x, map_y


def bilinear_remap(image, map_x, map_y):
    """
    Bilinear-interpolation remap with BORDER_CONSTANT = 0.

    Equivalent to cv2.remap(image, map_x, map_y, INTER_LINEAR,
                            borderMode=BORDER_CONSTANT, borderValue=0).
    """
    h, w = map_x.shape
    src_h, src_w = image.shape[:2]
    if image.ndim == 2:
        image = image[:, :, np.newaxis]

    sx = map_x.astype(np.float64)
    sy = map_y.astype(np.float64)

    x0 = np.floor(sx).astype(np.int64)
    y0 = np.floor(sy).astype(np.int64)

    fx = (sx - x0)[:, :, np.newaxis]
    fy = (sy - y0)[:, :, np.newaxis]

    def _lookup(yy, xx):
        valid = (xx >= 0) & (xx < src_w) & (yy >= 0) & (yy < src_h)
        yc = np.clip(yy, 0, src_h - 1)
        xc = np.clip(xx, 0, src_w - 1)
        vals = image[yc, xc].astype(np.float64)
        vals[~valid] = 0.0
        return vals

    result = (
        _lookup(y0, x0)         * (1.0 - fx) * (1.0 - fy) +
        _lookup(y0, x0 + 1)     * fx         * (1.0 - fy) +
        _lookup(y0 + 1, x0)     * (1.0 - fx) * fy +
        _lookup(y0 + 1, x0 + 1) * fx         * fy
    )

    return np.clip(np.round(result), 0, 255).astype(np.uint8)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main():
    # 1. Parse calibration from OpenCV FileStorage XML
    tree = ET.parse('/app/calibration.xml')
    root = tree.getroot()
    K = parse_opencv_matrix(root.find('camera_matrix'))
    dist = parse_opencv_matrix(root.find('dist_coeffs')).flatten().tolist()
    R = parse_opencv_matrix(root.find('rectification_rotation'))
    K_new = parse_opencv_matrix(root.find('new_camera_matrix'))
    target_frame = int(root.find('target_frame').text)
    print(f"Calibration loaded, target_frame={target_frame}")

    # 2. Inspect video with ffprobe
    width, height, num_frames = get_video_info('/app/input.mkv')
    print(f"Video: {width}x{height}, {num_frames} frames")

    # 3. Extract target frame with ffmpeg
    extract_frame('/app/input.mkv', target_frame, '/app/frame_02.png')
    print("Extracted target frame")

    # 4. Compute undistortion maps
    map_x, map_y = compute_maps(K, dist, R, K_new, width, height)
    np.save('/app/map_x.npy', map_x)
    np.save('/app/map_y.npy', map_y)
    print("Computed coordinate maps")

    # 5. Undistort target frame
    frame = np.array(Image.open('/app/frame_02.png'))
    undistorted = bilinear_remap(frame, map_x, map_y)
    Image.fromarray(undistorted).save('/app/undistorted_02.png')
    print("Undistorted target frame")

    # 6. Create montage with ImageMagick
    subprocess.run([
        'montage', '/app/frame_02.png', '/app/undistorted_02.png',
        '-tile', '2x1', '-geometry', '+0+0',
        '/app/montage.png'
    ], check=True, capture_output=True)
    print("Created montage")

    # 7. Undistort all frames and encode as lossless FFV1 MKV
    extract_all_frames('/app/input.mkv', '/tmp/raw_frames')
    os.makedirs('/tmp/und_frames', exist_ok=True)

    for i in range(num_frames):
        fname = f'/tmp/raw_frames/frame_{i + 1:03d}.png'
        f = np.array(Image.open(fname))
        u = bilinear_remap(f, map_x, map_y)
        Image.fromarray(u).save(f'/tmp/und_frames/frame_{i + 1:03d}.png')
        print(f"  Undistorted frame {i + 1}/{num_frames}")

    subprocess.run([
        'ffmpeg', '-y', '-framerate', '1',
        '-i', '/tmp/und_frames/frame_%03d.png',
        '-c:v', 'ffv1', '-pix_fmt', 'gbrp',
        '/app/undistorted_seq.mkv'
    ], check=True, capture_output=True)
    print("Encoded output video")

    print("Done — all outputs written to /app/")


if __name__ == "__main__":
    main()
