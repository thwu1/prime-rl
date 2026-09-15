// FDTD 3D Finite-Difference Time-Domain Stencil Computation
// Adapted from NVIDIA CUDA Samples - 3D star stencil with radius-4 padding
//

#include <cuda_runtime.h>
#include <cooperative_groups.h>
#include <iostream>
#include <fstream>
#include <cstring>

namespace cg = cooperative_groups;

#define RADIUS 4
#define k_blockDimX 32
#define k_blockDimMaxY 16

// Stencil coefficients stored in GPU constant memory
__constant__ float stencil[RADIUS + 1];

const int DIMX = 16;
const int DIMY = 16;
const int DIMZ = 16;

// 3D FDTD kernel using z-slice sweeping with register-based front/back buffers
// and shared memory tiling for the xy-plane
__global__ void
FiniteDifferencesKernel(float *output, const float *input,
                        const int dimx, const int dimy, const int dimz)
{
    bool      validr = true;
    bool      validw = true;
    const int gtidx  = blockIdx.x * blockDim.x + threadIdx.x;
    const int gtidy  = blockIdx.y * blockDim.y + threadIdx.y;
    const int ltidx  = threadIdx.x;
    const int ltidy  = threadIdx.y;
    const int workx  = blockDim.x;
    const int worky  = blockDim.y;

    // Handle to thread block group
    cg::thread_block cta = cg::this_thread_block();
    __shared__ float tile[k_blockDimMaxY + 2 * RADIUS][k_blockDimX + 2 * RADIUS];

    // Stride calculations for the padded volume
    const int stride_y = dimx + 2 * RADIUS;
    const int stride_z = stride_y * (dimy + 2 * RADIUS);

    int inputIndex  = 0;
    int outputIndex = 0;

    // Advance inputIndex to the start of the inner volume (skip halo in y and x)
    inputIndex += RADIUS * stride_y + RADIUS;

    // Advance inputIndex to the target element for this thread
    inputIndex += gtidy * stride_y + gtidx;

    // Register arrays for z-axis neighbors (front and back of current z-slice)
    float infront[RADIUS];
    float behind[RADIUS];
    float current;

    // Shared memory tile coordinates (offset by RADIUS for halo)
    const int tx = ltidx + RADIUS;
    const int ty = ltidy + RADIUS;

    // Bounds checking
    if ((gtidx >= dimx + RADIUS) || (gtidy >= dimy + RADIUS))
        validr = false;

    if ((gtidx >= dimx) || (gtidy >= dimy))
        validw = false;

    // Preload the "behind" data (z-planes before the first output plane)
    for (int i = RADIUS - 2; i >= 0; i--) {
        if (validr)
            behind[i] = input[inputIndex];
        inputIndex += stride_z;
    }

    if (validr)
        current = input[inputIndex];

    outputIndex = inputIndex;
    inputIndex += stride_z;

    // Preload the "infront" data (z-planes ahead of the current plane)
    for (int i = 0; i < RADIUS; i++) {
        if (validr)
            infront[i] = input[inputIndex];
        inputIndex += stride_z;
    }

    // Step through the xy-planes in the z dimension
#pragma unroll 9
    for (int iz = 0; iz < dimz; iz++) {
        // Advance the slice (shift register window along z)
        for (int i = RADIUS - 1; i > 0; i--)
            behind[i] = behind[i - 1];

        behind[0] = current;
        current    = infront[0];

#pragma unroll 4
        for (int i = 0; i < RADIUS - 1; i++)
            infront[i] = infront[i + 1];

        if (validr)
            infront[RADIUS - 1] = input[inputIndex];

        inputIndex  += stride_z;
        outputIndex += stride_z;
        cg::sync(cta);

        // Note: for work items on the boundary, the supplied index when
        // reading the halo may wrap to the previous/next row or xy-plane.
        // This is acceptable since (a) we disable output write for these
        // items and (b) there is at least one plane before/after.

        // Update the data slice in the shared memory tile
        // Load y-direction halos
        if (ltidy < RADIUS) {
            tile[ltidy][tx]                  = input[outputIndex - RADIUS * stride_y];
            tile[ltidy + worky + RADIUS][tx] = input[outputIndex + worky * stride_y];
        }

        // Load x-direction halos
        if (ltidx < RADIUS) {
            tile[ty][ltidx]                  = input[outputIndex - RADIUS];
            tile[ty][ltidx + workx + RADIUS] = input[outputIndex + workx];
        }

        tile[ty][tx] = current;
        cg::sync(cta);

        // Compute the output value using the star stencil
        float value = stencil[0] * current;
#pragma unroll 4
        for (int i = 1; i <= RADIUS; i++) {
            value += stencil[i]
                   * (infront[i - 1] + behind[i - 1]
                      + tile[ty - i][tx] + tile[ty + i][tx]
                      + tile[ty][tx - i] + tile[ty][tx + i]);
        }

        // Store the output value (only for valid inner positions)
        if (validw)
            output[outputIndex] = value;
    }
}

void read_binary(const std::string& filename, float* data, size_t size) {
    std::ifstream in(filename, std::ios::binary);
    if (!in) {
        std::cerr << "Cannot open: " << filename << std::endl;
        exit(1);
    }
    in.read(reinterpret_cast<char*>(data), size * sizeof(float));
    in.close();
}

void write_binary(const std::string& filename, const float* data, size_t size) {
    std::ofstream out(filename, std::ios::binary);
    if (!out) {
        std::cerr << "Cannot write: " << filename << std::endl;
        exit(1);
    }
    out.write(reinterpret_cast<const char*>(data), size * sizeof(float));
    out.close();
}

int main() {
    const int outer_dimx = DIMX + 2 * RADIUS;
    const int outer_dimy = DIMY + 2 * RADIUS;
    const int outer_dimz = DIMZ + 2 * RADIUS;
    const size_t volume_size = outer_dimx * outer_dimy * outer_dimz;
    const size_t bytes = volume_size * sizeof(float);
    const size_t stencil_bytes = (RADIUS + 1) * sizeof(float);

    float* h_input = new float[volume_size];
    float* h_output = new float[volume_size];
    float* h_stencil = new float[RADIUS + 1];

    // Read input volume and stencil coefficients
    read_binary("./data/fdtd_input.bin", h_input, volume_size);
    read_binary("./data/fdtd_stencil.bin", h_stencil, RADIUS + 1);

    // Initialize output to zero
    std::memset(h_output, 0, bytes);

    float *d_input, *d_output;
    cudaMalloc(&d_input, bytes);
    cudaMalloc(&d_output, bytes);

    cudaMemcpy(d_input, h_input, bytes, cudaMemcpyHostToDevice);
    cudaMemcpy(d_output, h_output, bytes, cudaMemcpyHostToDevice);
    cudaMemcpyToSymbol(stencil, h_stencil, stencil_bytes);

    dim3 dimBlock(k_blockDimX, k_blockDimMaxY);
    dim3 dimGrid((DIMX + dimBlock.x - 1) / dimBlock.x,
                 (DIMY + dimBlock.y - 1) / dimBlock.y);

    FiniteDifferencesKernel<<<dimGrid, dimBlock>>>(
        d_output, d_input, DIMX, DIMY, DIMZ);

    cudaMemcpy(h_output, d_output, bytes, cudaMemcpyDeviceToHost);

    write_binary("./data/fdtd_output.bin", h_output, volume_size);

    cudaFree(d_input);
    cudaFree(d_output);
    delete[] h_input;
    delete[] h_output;
    delete[] h_stencil;

    return 0;
}
