NIST NFIQ2 Reference Source Code (Excerpts)
============================================

These files are excerpted from the official NIST NFIQ2 C++ implementation
(github.com/usnistgov/NFIQ2) for algorithm reference. They are NOT meant to
be compiled; use them to understand the correct algorithm behavior.

Files:

  common_functions.cpp - Shared utilities:
    computeNumericalGradientX / computeNumericalGradients - gradient computation
    diffGrad - row-wise gradient used by covcoef
    covcoef - gradient covariance coefficients (a, b, c)
    ridgeorient - ridge orientation angle from covariance
    ridgesegment - foreground/background segmentation
    getRotatedBlock - nearest-neighbor block rotation via cv::warpAffine
    addHistogramFeatures - 10-bin histogram computation with mean/stddev

  fda.cpp - Frequency Domain Analysis (FDA) quality measure
    computeFeatureData - main loop: offset grid iteration, mask check, rotation
    fda() function - per-block DFT-based ridge periodicity scoring

  ocl.cpp - Orientation Certainty Level (OCL) quality measure
    computeFeatureData - block loop over BS_OCL x BS_OCL grid
    getOCLValueOfBlock - eigenvalue-based orientation certainty per block

Key OpenCV conventions used in the C++ code:
  - cv::Mat indexing: mat.at<T>(row, col) — row-major like numpy
  - cv::Range(start, end) — half-open interval [start, end)
  - cv::Rect(x, y, width, height) — (col, row, w, h)
  - cv::warpAffine with cv::INTER_NEAREST for rotation
