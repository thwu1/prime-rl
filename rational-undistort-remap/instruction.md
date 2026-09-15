A distorted camera video is at `/app/input.mkv` and camera calibration data is in `/app/calibration.xml`, stored in OpenCV's FileStorage XML format. The calibration file contains a 3×3 intrinsic matrix (`camera_matrix`), 8-parameter rational distortion coefficients (`dist_coeffs`: [k1, k2, p1, p2, k3, k4, k5, k6]), a rectification rotation matrix (`rectification_rotation`), a new camera matrix (`new_camera_matrix`), and a `target_frame` index (0-based). The video's resolution and frame count are **not** in the calibration file — inspect the video to determine them.

Implement a complete undistortion and rectification pipeline from scratch that corrects lens distortion and applies the stereo rectification transform using the provided calibration parameters. The remapping must use bilinear interpolation with zero-valued out-of-bounds handling. Your implementation must **not** use OpenCV (`cv2`) or any library wrapping it. NumPy and Pillow are permitted.

Produce all of the following outputs:

- `/app/frame_02.png` — the target frame extracted from the video
- `/app/undistorted_02.png` — the undistorted and rectified target frame (same dimensions as input)
- `/app/map_x.npy` — float32 array of shape (H, W) giving the source x-coordinate (column) for each destination pixel
- `/app/map_y.npy` — float32 array of shape (H, W) giving the source y-coordinate (row) for each destination pixel
- `/app/montage.png` — side-by-side comparison: original target frame (left), undistorted frame (right), tiled 2×1 with no padding, resulting dimensions exactly 2W × H
- `/app/undistorted_seq.mkv` — all video frames undistorted and encoded as lossless video in MKV container, preserving exact RGB pixel values

Output is verified against a reference implementation with tight numerical tolerance on coordinate maps (max error < 0.01), remapped pixels (max error < 8, mean < 1.5), montage composition, and per-frame video accuracy.