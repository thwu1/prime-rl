"""Generate a synthetic 3D medical phantom with ellipsoidal structures.

Creates a volume with known spatial metadata (anisotropic spacing, non-zero origin,
rotated direction cosines) and embedded structures for analysis pipeline testing.

Uses SimpleITK for image I/O to guarantee correct MetaImage format.
"""
import numpy as np
import SimpleITK as sitk
import os


def main():
    os.makedirs('/app', exist_ok=True)

    np.random.seed(42)

    # Volume dimensions (voxels)
    nx, ny, nz = 128, 128, 80

    # Anisotropic spacing (mm) - z-spacing is 2.4x larger than xy
    spacing = (0.5, 0.5, 1.2)

    # Non-zero origin (mm)
    origin = (10.0, -5.0, 20.0)

    # Direction cosine matrix: 20-degree rotation about z-axis
    # Physical coords: world = origin + D @ diag(spacing) @ index
    theta = np.radians(20)
    cos_t = float(np.cos(theta))
    sin_t = float(np.sin(theta))
    direction = [cos_t, sin_t, 0.0, -sin_t, cos_t, 0.0, 0.0, 0.0, 1.0]

    # Background: mean=40, noise std=10
    phantom = np.random.normal(40, 10, (nz, ny, nx)).astype(np.float32)

    # Structure definitions: (center_x, center_y, center_z, radius_x, radius_y, radius_z, intensity)
    # All values in voxel coordinates.
    # Structures are well-separated (>20 voxel gap) to prevent noise bridging.
    structures = [
        (30, 30, 20, 12, 10, 6, 180),
        (95, 30, 55, 10,  8, 5, 200),
        (30, 95, 50,  8,  7, 5, 190),
        (95, 95, 25,  9,  8, 4, 210),
        (60, 60, 65,  7,  7, 4, 215),
        (60, 30, 40,  8,  6, 5, 195),
    ]

    # Coordinate grids (z, y, x ordering for numpy)
    z_grid, y_grid, x_grid = np.mgrid[0:nz, 0:ny, 0:nx]

    for cx, cy, cz, rx, ry, rz, intensity in structures:
        # Ellipsoid equation: (x-cx)^2/rx^2 + (y-cy)^2/ry^2 + (z-cz)^2/rz^2 <= 1
        dist_sq = (
            ((x_grid - cx) / rx) ** 2
            + ((y_grid - cy) / ry) ** 2
            + ((z_grid - cz) / rz) ** 2
        )
        mask = dist_sq <= 1.0
        n_voxels = int(np.sum(mask))
        # Structure voxels: target intensity with low noise (std=5)
        phantom[mask] = intensity + np.random.normal(0, 5, n_voxels).astype(np.float32)

    phantom = np.clip(phantom, 0, 300).astype(np.float32)

    # Create SimpleITK image from numpy array (handles axis reversal automatically)
    img = sitk.GetImageFromArray(phantom)
    img.SetSpacing(spacing)
    img.SetOrigin(origin)
    img.SetDirection(direction)

    sitk.WriteImage(img, '/app/phantom.mha')

    print(f"Phantom written to /app/phantom.mha")
    print(f"  Shape: {nx} x {ny} x {nz} voxels")
    print(f"  Spacing: {spacing} mm")
    print(f"  Origin: {origin} mm")
    print(f"  Direction: {np.degrees(theta):.1f} deg rotation about z")
    print(f"  Structures: {len(structures)}")


if __name__ == '__main__':
    main()
