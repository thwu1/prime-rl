`/app/phantom.mha` is a 3D calibration phantom image (MetaImage format) containing a regular grid of spherical fiducial markers. The phantom was acquired from a scanner that introduces unknown geometric distortion, displacing markers from their ideal grid positions. The distortion follows a 2nd-order polynomial model whose coefficients are unknown.

The full phantom specification — ideal grid geometry, image parameters, distortion model type, quality acceptance criteria, and required output schema — is in `/app/calibration_spec.json`.

Create `/app/calibrate.py` that reads the phantom image, detects all fiducial markers and computes their physical-space centroids, matches each detected marker to its corresponding ideal grid position, estimates the polynomial distortion model from the observed displacements, measures image signal-to-noise ratio, evaluates the phantom against the quality acceptance criteria, and writes the complete results to `/app/calibration_report.json` in the format specified by the schema in the spec.

Run your script to produce the report.