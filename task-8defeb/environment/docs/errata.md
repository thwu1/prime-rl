# ISLES-26 Evaluation Errata

The following changes apply to the current (2026) edition relative to prior ISLES and ATLAS challenge editions. The included reference evaluation script (`reference_eval.py`) implements the **prior** methodology and should not be used directly.

## 1. Lesion Detection Criterion

Previous editions used the `panoptica` library's IoU-threshold matching (`NaiveThresholdMatching(matching_threshold=0.2)`) to determine whether a predicted lesion instance matches a ground truth lesion instance. Under this approach, a match requires the intersection-over-union between a predicted component and a ground truth component to exceed 0.2.

The current edition uses the simpler **any-voxel-overlap** criterion. A ground truth lesion (connected component) is considered detected (true positive) if at least one predicted foreground voxel falls within its spatial extent. A predicted connected component that does not overlap any ground truth component is a false positive. This change was made to better capture clinical detection performance for small lesions where even partial detection is clinically meaningful.

## 2. Volume Units

ATLAS R2.0 reported absolute volume difference in raw voxel counts. The current edition reports in **milliliters** (mL). Convert using per-axis voxel dimensions from the NIfTI header: volume_ml = voxel_count × (dim_x × dim_y × dim_z) / 1000.

## 3. Connected Component Connectivity

3D connected component labeling uses the **6-connected** (face-adjacent) neighborhood, not 26-connected (full neighborhood). This matches `scipy.ndimage.label` with default structuring element.

## 4. Volume Computation in Reference Code

The reference `compute_absolute_volume_difference` function takes a single scalar `voxel_size` parameter (the product of all three voxel dimensions). The current edition requires extracting per-axis dimensions from the NIfTI header independently and computing the per-voxel volume as their product. The result is equivalent when done correctly, but implementations must source voxel dimensions from the image header rather than any external configuration.
