#pragma once
// Compute pairwise Pearson correlation matrix.
// input:  row-major n x d matrix (n vectors of dimension d)
// output: row-major n x n correlation matrix
//         output[i*n+j] = Pearson correlation between row i and row j
void correlate(int n, int d, const float* input, float* output);
