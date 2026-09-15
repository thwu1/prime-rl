#!/usr/bin/env python3
"""Generate calibration XML and frame images for the undistort-rectify-pipeline task."""
import math
import os
from PIL import Image


def rodrigues_to_matrix(rvec):
    """Convert a Rodrigues rotation vector to a 3x3 rotation matrix."""
    theta = math.sqrt(sum(x * x for x in rvec))
    if theta < 1e-10:
        return [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    k = [x / theta for x in rvec]
    c = math.cos(theta)
    s = math.sin(theta)
    t = 1 - c
    kx, ky, kz = k
    return [
        [c + t * kx * kx,     t * kx * ky - s * kz, t * kx * kz + s * ky],
        [t * ky * kx + s * kz, c + t * ky * ky,      t * ky * kz - s * kx],
        [t * kz * kx - s * ky, t * kz * ky + s * kx, c + t * kz * kz],
    ]


def fmt_matrix(matrix_2d):
    """Format a 2D list as space-separated scientific notation."""
    return ' '.join(f'{v:.16e}' for row in matrix_2d for v in row)


def fmt_vector(vec):
    """Format a 1D list as space-separated scientific notation."""
    return ' '.join(f'{v:.16e}' for v in vec)


def write_opencv_filestorage_xml(filepath, K, dist, R, K_new, target_frame):
    """Write calibration data in OpenCV FileStorage XML format.

    This is the XML dialect that cv2.FileStorage reads/writes — matrices
    carry a type_id=\"opencv-matrix\" attribute with rows/cols/dt/data children.
    """
    lines = [
        '<?xml version="1.0"?>',
        '<opencv_storage>',
        '<camera_matrix type_id="opencv-matrix">',
        '  <rows>3</rows>',
        '  <cols>3</cols>',
        '  <dt>d</dt>',
        '  <data>' + fmt_matrix(K) + '</data>',
        '</camera_matrix>',
        '<dist_coeffs type_id="opencv-matrix">',
        '  <rows>1</rows>',
        '  <cols>8</cols>',
        '  <dt>d</dt>',
        '  <data>' + fmt_vector(dist) + '</data>',
        '</dist_coeffs>',
        '<rectification_rotation type_id="opencv-matrix">',
        '  <rows>3</rows>',
        '  <cols>3</cols>',
        '  <dt>d</dt>',
        '  <data>' + fmt_matrix(R) + '</data>',
        '</rectification_rotation>',
        '<new_camera_matrix type_id="opencv-matrix">',
        '  <rows>3</rows>',
        '  <cols>3</cols>',
        '  <dt>d</dt>',
        '  <data>' + fmt_matrix(K_new) + '</data>',
        '</new_camera_matrix>',
        f'<target_frame>{target_frame}</target_frame>',
        '</opencv_storage>',
    ]
    with open(filepath, 'w') as f:
        f.write('\n'.join(lines) + '\n')


def main():
    WIDTH, HEIGHT = 640, 480
    NUM_FRAMES = 5

    # Camera intrinsics (principal point at image centre)
    K = [[800.0, 0.0, 320.0],
         [0.0, 800.0, 240.0],
         [0.0, 0.0, 1.0]]

    # 8-parameter rational distortion: [k1, k2, p1, p2, k3, k4, k5, k6]
    DIST_COEFFS = [-0.3412, 0.1839, 0.00231, -0.00154,
                   -0.0567, 0.2143, -0.1287, 0.0342]

    # Non-trivial rectification rotation (~11 degrees)
    R = rodrigues_to_matrix([0.15, -0.10, 0.08])

    K_NEW = [[750.0, 0.0, 320.0],
             [0.0, 750.0, 240.0],
             [0.0, 0.0, 1.0]]

    TARGET_FRAME = 2

    write_opencv_filestorage_xml(
        '/app/calibration.xml', K, DIST_COEFFS, R, K_NEW, TARGET_FRAME
    )

    # Generate frames with per-frame variation
    os.makedirs('/tmp/frames', exist_ok=True)
    for fi in range(NUM_FRAMES):
        data = bytearray(WIDTH * HEIGHT * 3)
        phase = fi * 0.4
        for y in range(HEIGHT):
            gy = int(255 * y / (HEIGHT - 1))
            cos_y = math.cos(y * 0.02 + phase)
            for x in range(WIDTH):
                idx = (y * WIDTH + x) * 3
                checker = ((x // 40) + (y // 40) + fi) % 2
                gx = int(255 * x / (WIDTH - 1))
                b = int(128 + 127 * math.sin(x * 0.02 + phase) * cos_y)
                b = max(0, min(255, b))
                if checker:
                    data[idx] = gx
                    data[idx + 1] = gy
                    data[idx + 2] = b
                else:
                    data[idx] = 255 - gx
                    data[idx + 1] = 255 - gy
                    data[idx + 2] = max(0, min(255, 255 - b))
        img = Image.frombytes("RGB", (WIDTH, HEIGHT), bytes(data))
        img.save(f'/tmp/frames/frame_{fi:03d}.png')

    print(f"Generated {NUM_FRAMES} frames and calibration.xml")


if __name__ == "__main__":
    main()
