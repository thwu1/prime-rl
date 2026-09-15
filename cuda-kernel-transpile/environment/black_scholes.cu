// Black-Scholes European Option Pricing
// GPU kernel using polynomial approximation for the cumulative normal distribution
//

#include <cuda_runtime.h>
#include <device_launch_parameters.h>
#include <iostream>
#include <fstream>
#include <cmath>

#define OPT_N 2048
#define RISKFREE 0.02f
#define VOLATILITY 0.30f

////////////////////////////////////////////////////////////////////////////////
// Polynomial approximation of cumulative normal distribution function
// Based on Abramowitz & Stegun formula 26.2.17
////////////////////////////////////////////////////////////////////////////////
__device__ inline float cndGPU(float d)
{
    const float A1       = 0.31938153f;
    const float A2       = -0.356563782f;
    const float A3       = 1.781477937f;
    const float A4       = -1.821255978f;
    const float A5       = 1.330274429f;
    const float RSQRT2PI = 0.39894228040143267793994605993438f;

    float K = __fdividef(1.0f, (1.0f + 0.2316419f * fabsf(d)));

    float cnd = RSQRT2PI * __expf(-0.5f * d * d)
              * (K * (A1 + K * (A2 + K * (A3 + K * (A4 + K * A5)))));

    if (d > 0)
        cnd = 1.0f - cnd;

    return cnd;
}

////////////////////////////////////////////////////////////////////////////////
// Black-Scholes formula for both call and put
////////////////////////////////////////////////////////////////////////////////
__device__ inline void BlackScholesBodyGPU(float &CallResult,
                                           float &PutResult,
                                           float  S, // Stock price
                                           float  X, // Option strike
                                           float  T, // Option years
                                           float  R, // Riskless rate
                                           float  V  // Volatility rate
)
{
    float sqrtT, expRT;
    float d1, d2, CNDD1, CNDD2;

    sqrtT = __fdividef(1.0F, rsqrtf(T));
    d1    = __fdividef(__logf(S / X) + (R + 0.5f * V * V) * T, V * sqrtT);
    d2    = d1 - V * sqrtT;

    CNDD1 = cndGPU(d1);
    CNDD2 = cndGPU(d2);

    // Calculate Call and Put simultaneously
    expRT      = __expf(-R * T);
    CallResult = S * CNDD1 - X * expRT * CNDD2;
    PutResult  = X * expRT * (1.0f - CNDD2) - S * (1.0f - CNDD1);
}

////////////////////////////////////////////////////////////////////////////////
// Process array of options on GPU using float2 vectorization
// Each thread processes 2 options for increased ILP
////////////////////////////////////////////////////////////////////////////////
__global__ void BlackScholesGPU(float2 *__restrict d_CallResult,
                                float2 *__restrict d_PutResult,
                                float2 *__restrict d_StockPrice,
                                float2 *__restrict d_OptionStrike,
                                float2 *__restrict d_OptionYears,
                                float Riskfree,
                                float Volatility,
                                int   optN)
{
    const int opt = blockDim.x * blockIdx.x + threadIdx.x;

    // Process 2 options per thread using float2 for coalesced memory access
    if (opt < (optN / 2)) {
        float callResult1, callResult2;
        float putResult1, putResult2;

        // Process first element of float2
        BlackScholesBodyGPU(callResult1, putResult1,
                            d_StockPrice[opt].x,
                            d_OptionStrike[opt].x,
                            d_OptionYears[opt].x,
                            Riskfree, Volatility);

        // Process second element of float2
        BlackScholesBodyGPU(callResult2, putResult2,
                            d_StockPrice[opt].y,
                            d_OptionStrike[opt].y,
                            d_OptionYears[opt].y,
                            Riskfree, Volatility);

        d_CallResult[opt] = make_float2(callResult1, callResult2);
        d_PutResult[opt]  = make_float2(putResult1, putResult2);
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
    int optN = OPT_N;
    size_t bytes = optN * sizeof(float);

    float *h_S = new float[optN];
    float *h_X = new float[optN];
    float *h_T = new float[optN];
    float *h_Call = new float[optN];
    float *h_Put = new float[optN];

    read_binary("data/stock_price.bin", h_S, optN);
    read_binary("data/option_strike.bin", h_X, optN);
    read_binary("data/option_years.bin", h_T, optN);

    float *d_S, *d_X, *d_T, *d_Call, *d_Put;
    cudaMalloc(&d_S, bytes);
    cudaMalloc(&d_X, bytes);
    cudaMalloc(&d_T, bytes);
    cudaMalloc(&d_Call, bytes);
    cudaMalloc(&d_Put, bytes);

    cudaMemcpy(d_S, h_S, bytes, cudaMemcpyHostToDevice);
    cudaMemcpy(d_X, h_X, bytes, cudaMemcpyHostToDevice);
    cudaMemcpy(d_T, h_T, bytes, cudaMemcpyHostToDevice);

    // Launch: each thread processes 2 options via float2 vectorization
    int threads = 128;
    int blocks = (optN / 2 + threads - 1) / threads;

    // Cast float* to float2* for the kernel
    BlackScholesGPU<<<blocks, threads>>>(
        (float2*)d_Call, (float2*)d_Put,
        (float2*)d_S, (float2*)d_X, (float2*)d_T,
        RISKFREE, VOLATILITY, optN);

    cudaMemcpy(h_Call, d_Call, bytes, cudaMemcpyDeviceToHost);
    cudaMemcpy(h_Put, d_Put, bytes, cudaMemcpyDeviceToHost);

    write_binary("data/call_out.bin", h_Call, optN);
    write_binary("data/put_out.bin", h_Put, optN);

    cudaFree(d_S); cudaFree(d_X); cudaFree(d_T);
    cudaFree(d_Call); cudaFree(d_Put);
    delete[] h_S; delete[] h_X; delete[] h_T;
    delete[] h_Call; delete[] h_Put;

    return 0;
}
