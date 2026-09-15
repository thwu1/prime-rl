#!/usr/bin/env python3
"""Generate task data files for roofline model construction task."""
import os, json

os.makedirs('/app/data', exist_ok=True)

# ---------------------------------------------------------------------------
# ERT configuration file
# ---------------------------------------------------------------------------
with open('/app/data/ert.conf', 'w') as f:
    f.write(r"""# ERT configuration file for Haswell E5-2630 v3 characterization run
# See https://bitbucket.org/berkeleylab/cs-roofline-toolkit/

ERT_RESULTS Results.haswell-e5-2630v3-node07

ERT_SPEC_GBYTES_DRAM  59.7
ERT_SPEC_GFLOPS       120.0

ERT_DRIVER  driver1
ERT_KERNEL  kernel1

ERT_MPI         False
ERT_MPI_CFLAGS
ERT_MPI_LDFLAGS

ERT_OPENMP         True
ERT_OPENMP_CFLAGS  -fopenmp
ERT_OPENMP_LDFLAGS -fopenmp

ERT_FLOPS   1,2,4,8,16,32,64,128,256
ERT_ALIGN   64

ERT_CC      gcc
ERT_CFLAGS  -O3 -march=haswell
ERT_LD      gcc
ERT_LDFLAGS
ERT_LDLIBS  -lm

ERT_PRECISION FP64

ERT_RUN     export OMP_NUM_THREADS=ERT_OPENMP_THREADS; ERT_CODE

ERT_PROCS_THREADS  8
ERT_MPI_PROCS      1
ERT_OPENMP_THREADS 8

ERT_NUM_EXPERIMENTS 3
ERT_MEMORY_MAX 268435456
ERT_WORKING_SET_MIN 1
ERT_TRIALS_MIN 1

ERT_GNUPLOT gnuplot
""")

# ---------------------------------------------------------------------------
# Hardware topology (hwloc v2 XML format from lstopo --of xml)
# ---------------------------------------------------------------------------
def generate_hwloc_xml():
    lines = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append('<!DOCTYPE topology SYSTEM "hwloc2.dtd">')
    lines.append('<topology version="2">')
    lines.append('  <object type="Machine" os_index="0" total_memory="67448438784">')
    lines.append('    <info name="Backend" value="Linux"/>')
    lines.append('    <info name="LinuxCgroup" value="/"/>')
    lines.append('    <info name="Architecture" value="x86_64"/>')
    lines.append('    <info name="OSName" value="Linux"/>')
    lines.append('    <info name="OSRelease" value="5.15.0-94-generic"/>')
    lines.append('    <info name="OSVersion" value="#104-Ubuntu SMP Tue Jan 9 15:25:40 UTC 2024"/>')
    lines.append('    <info name="HostName" value="haswell-node07"/>')
    lines.append('    <info name="DMIProductName" value="PowerEdge R630"/>')
    lines.append('    <info name="DMIProductVersion" value=""/>')
    lines.append('    <info name="DMIBoardVendor" value="Dell Inc."/>')
    lines.append('    <info name="DMIBoardName" value="0CNCJW"/>')
    lines.append('    <object type="NUMANode" os_index="0" local_memory="67448438784">')
    lines.append('      <page_type size="4096" count="16469960"/>')
    lines.append('      <page_type size="2097152" count="0"/>')
    lines.append('    </object>')
    lines.append('    <object type="Package" os_index="0">')
    lines.append('      <info name="CPUVendor" value="GenuineIntel"/>')
    lines.append('      <info name="CPUFamilyNumber" value="6"/>')
    lines.append('      <info name="CPUModelNumber" value="63"/>')
    lines.append('      <info name="CPUModel" value="Intel(R) Xeon(R) CPU E5-2630 v3 @ 2.40GHz"/>')
    lines.append('      <info name="CPUStepping" value="2"/>')
    lines.append('      <object type="L3Cache" os_index="0" cache_size="20971520" cache_linesize="64" cache_associativity="20" cache_type="0" depth="3">')
    # Generate 8 cores, each with L2 -> L1d + L1i
    for core_id in range(8):
        pu1 = core_id
        pu2 = core_id + 8
        lines.append(f'        <object type="L2Cache" os_index="{core_id}" cache_size="262144" cache_linesize="64" cache_associativity="8" cache_type="0" depth="2">')
        lines.append(f'          <object type="L1Cache" os_index="{core_id}" cache_size="32768" cache_linesize="64" cache_associativity="8" cache_type="1" depth="1">')
        lines.append(f'            <object type="Core" os_index="{core_id}">')
        lines.append(f'              <object type="PU" os_index="{pu1}"/>')
        lines.append(f'              <object type="PU" os_index="{pu2}"/>')
        lines.append(f'            </object>')
        lines.append(f'          </object>')
        lines.append(f'          <object type="L1iCache" os_index="{core_id}" cache_size="32768" cache_linesize="64" cache_associativity="8" cache_type="2" depth="1"/>')
        lines.append(f'        </object>')
    lines.append('      </object>')
    lines.append('    </object>')
    lines.append('  </object>')
    lines.append('</topology>')
    return '\n'.join(lines) + '\n'

with open('/app/data/hwloc_topology.xml', 'w') as f:
    f.write(generate_hwloc_xml())

# ---------------------------------------------------------------------------
# ERT bandwidth sweep data (GnuPlot tab-separated format)
# ---------------------------------------------------------------------------
bw_lines = [
    "# ERT v1.1.0 Bandwidth Results",
    "# MACHINE haswell-e5-2630v3-node07.cluster.hpc",
    "# KERNEL  kernel1 (driver1)",
    "# DATE    2024-03-15T14:23:07Z",
    "# CONFIG  MPI_PROCS=1 OMP_THREADS=8",
    "# CONFIG  PRECISION=FP64",
    "# CONFIG  WORKING_SET_MIN=1 MEMORY_MAX=268435456",
    "# CONFIG  TRIALS_MIN=1 NUM_EXPERIMENTS=3",
    "# CONFIG  FLOPS_PER_ELEMENT=1",
    "#",
    "# Working set sizes are in ELEMENTS.",
    "# See ert.conf for precision and byte-per-element details.",
    "#",
    "# ws_elements\ttrial\tbandwidth_GBs",
]
bw_data = [
    (16, 1, 420.5), (16, 2, 445.2), (16, 3, 450.0),
    (32, 1, 442.1), (32, 2, 448.0), (32, 3, 441.5),
    (64, 1, 438.7), (64, 2, 446.0), (64, 3, 440.2),
    (128, 1, 435.3), (128, 2, 442.0), (128, 3, 437.8),
    (256, 1, 430.1), (256, 2, 438.5), (256, 3, 434.2),
    (512, 1, 425.4), (512, 2, 434.0), (512, 3, 428.7),
    (1024, 1, 418.2), (1024, 2, 428.5), (1024, 3, 422.1),
    (2048, 1, 410.5), (2048, 2, 420.3), (2048, 3, 414.7),
    (4096, 1, 175.2), (4096, 2, 180.0), (4096, 3, 177.8),
    (8192, 1, 172.4), (8192, 2, 178.5), (8192, 3, 175.1),
    (16384, 1, 168.3), (16384, 2, 174.2), (16384, 3, 170.8),
    (32768, 1, 51.8), (32768, 2, 54.0), (32768, 3, 52.5),
    (65536, 1, 50.2), (65536, 2, 53.1), (65536, 3, 51.4),
    (131072, 1, 48.7), (131072, 2, 51.5), (131072, 3, 49.8),
    (262144, 1, 46.3), (262144, 2, 49.2), (262144, 3, 47.5),
    (524288, 1, 44.1), (524288, 2, 47.0), (524288, 3, 45.2),
    (1048576, 1, 42.5), (1048576, 2, 45.1), (1048576, 3, 43.4),
    (2097152, 1, 40.8), (2097152, 2, 43.5), (2097152, 3, 41.7),
    (4194304, 1, 27.2), (4194304, 2, 28.0), (4194304, 3, 27.5),
    (8388608, 1, 26.5), (8388608, 2, 27.3), (8388608, 3, 26.8),
    (16777216, 1, 25.8), (16777216, 2, 26.7), (16777216, 3, 26.1),
    (33554432, 1, 25.2), (33554432, 2, 26.0), (33554432, 3, 25.5),
]
with open('/app/data/ert_bandwidth.dat', 'w') as f:
    for line in bw_lines:
        f.write(line + '\n')
    for ws, trial, bw in bw_data:
        f.write(f"{ws}\t{trial}\t{bw}\n")

# ---------------------------------------------------------------------------
# ERT compute sweep data (GnuPlot tab-separated format)
# ---------------------------------------------------------------------------
compute_lines = [
    "# ERT v1.1.0 Compute Results",
    "# MACHINE haswell-e5-2630v3-node07.cluster.hpc",
    "# KERNEL  kernel1 (driver1)",
    "# DATE    2024-03-15T14:28:41Z",
    "# CONFIG  MPI_PROCS=1 OMP_THREADS=8",
    "# CONFIG  PRECISION=FP64",
    "# CONFIG  FLOPS_SWEEP=1,2,4,8,16,32,64,128,256",
    "# CONFIG  WORKING_SET=512 (elements, fixed for compute sweep)",
    "#",
    "# Working set held constant; flops_per_element varied.",
    "# See ert.conf for precision and byte-per-element details.",
    "#",
    "# flops_per_element\ttrial\tachieved_GFLOPs",
]
compute_data = [
    (1, 1, 3.8), (1, 2, 4.2), (1, 3, 4.0),
    (2, 1, 7.9), (2, 2, 8.3), (2, 3, 8.1),
    (4, 1, 15.8), (4, 2, 16.4), (4, 3, 16.0),
    (8, 1, 30.5), (8, 2, 31.5), (8, 3, 30.9),
    (16, 1, 51.2), (16, 2, 52.8), (16, 3, 51.9),
    (32, 1, 60.8), (32, 2, 62.4), (32, 3, 61.5),
    (64, 1, 62.5), (64, 2, 64.0), (64, 3, 63.1),
    (128, 1, 63.5), (128, 2, 64.2), (128, 3, 63.8),
    (256, 1, 63.0), (256, 2, 64.2), (256, 3, 63.4),
]
with open('/app/data/ert_compute.dat', 'w') as f:
    for line in compute_lines:
        f.write(line + '\n')
    for fpe, trial, gf in compute_data:
        f.write(f"{fpe}\t{trial}\t{gf}\n")

# ---------------------------------------------------------------------------
# STREAM benchmark output
# ---------------------------------------------------------------------------
with open('/app/data/stream_output.txt', 'w') as f:
    f.write("""-------------------------------------------------------------
STREAM version $Revision: 5.10 $
-------------------------------------------------------------
This system uses 8 bytes per array element.
-------------------------------------------------------------
Array size = 10000000 (elements), Offset = 0 (elements)
Memory per array = 76.3 MiB (= 0.1 GiB).
Total memory required = 228.9 MiB (= 0.2 GiB).
Each kernel will be executed 10 times.
 The *best* time for each kernel (excluding the first iteration)
 will be used to compute the reported bandwidth.
-------------------------------------------------------------
Number of Threads requested = 12
Number of Threads counted = 12
-------------------------------------------------------------
Your clock granularity/precision appears to be 1 microseconds.
Each test below will take on the order of 9120 microseconds.
   (= 9120 clock ticks)
Increase the size of the arrays if this shows that
you are not getting at least 20 clock ticks per test.
-------------------------------------------------------------
WARNING -- The above is only a rough guideline.
For best results, please be sure you know the
precision of your system timer.
-------------------------------------------------------------
Function    Best Rate MB/s  Avg time     Min time     Max time
Copy:           18500.0     0.009241     0.008649     0.009534
Scale:          18200.0     0.009421     0.008791     0.009682
Add:            20700.0     0.012489     0.011594     0.012841
Triad:          20550.0     0.012612     0.011679     0.012973
-------------------------------------------------------------
Solution Validates: avg error less than 1.000000e-13 on all three arrays
-------------------------------------------------------------
""")

# ---------------------------------------------------------------------------
# Application kernels
# ---------------------------------------------------------------------------
kernels = [
    {
        "name": "stencil_3d",
        "description": "7-point 3D stencil on 512^3 grid, 5 sweeps",
        "total_flops": 1.2e9,
        "bytes_per_level": {
            "L1": 6.0e9, "L2": 3.0e9, "L3": 1.5e9, "DRAM": 6.0e8
        }
    },
    {
        "name": "dense_matmul",
        "description": "Tiled DGEMM 1024x1024, block size 64",
        "total_flops": 8.0e9,
        "bytes_per_level": {
            "L1": 2.0e10, "L2": 4.0e9, "L3": 8.0e8, "DRAM": 2.0e8
        }
    },
    {
        "name": "sparse_mv",
        "description": "SpMV with irregular access pattern, 10M nonzeros",
        "total_flops": 5.0e8,
        "bytes_per_level": {
            "L1": 2.0e10, "L2": 1.0e10, "L3": 5.0e9, "DRAM": 4.0e9
        }
    },
    {
        "name": "fft_radix2",
        "description": "Radix-2 FFT of 2^24 complex doubles",
        "total_flops": 2.5e9,
        "bytes_per_level": {
            "L1": 2.5e10, "L2": 5.0e9, "L3": 1.25e9, "DRAM": 5.0e8
        }
    },
    {
        "name": "particle_force",
        "description": "Direct N-body force calculation, N=50000",
        "total_flops": 1.0e10,
        "bytes_per_level": {
            "L1": 4.0e9, "L2": 1.0e9, "L3": 2.5e8, "DRAM": 5.0e7
        }
    }
]
with open('/app/data/kernels.json', 'w') as f:
    json.dump(kernels, f, indent=4)

# ---------------------------------------------------------------------------
# Output JSON schema
# ---------------------------------------------------------------------------
schema = {
    "type": "object",
    "required": ["empirical_peak_gflops", "memory_levels", "stream_corrected", "kernel_analysis"],
    "properties": {
        "empirical_peak_gflops": {
            "type": "number",
            "description": "Empirical peak compute throughput in GFLOP/s"
        },
        "memory_levels": {
            "type": "object",
            "required": ["L1", "L2", "L3", "DRAM"],
            "additionalProperties": {"$ref": "#/definitions/memory_level"}
        },
        "stream_corrected": {
            "type": "object",
            "required": ["Copy", "Scale", "Add", "Triad"],
            "additionalProperties": {"$ref": "#/definitions/stream_kernel"}
        },
        "kernel_analysis": {
            "type": "array",
            "items": {"$ref": "#/definitions/kernel_entry"}
        }
    },
    "definitions": {
        "memory_level": {
            "type": "object",
            "required": ["peak_bandwidth_gb_per_s", "ridge_point_flop_per_byte"],
            "properties": {
                "peak_bandwidth_gb_per_s": {
                    "type": "number",
                    "description": "Empirical peak bandwidth at this cache level in GB/s"
                },
                "ridge_point_flop_per_byte": {
                    "type": "number",
                    "description": "Ridge point arithmetic intensity at this level (FLOP/byte)"
                }
            }
        },
        "stream_kernel": {
            "type": "object",
            "required": ["reported_mb_per_s", "corrected_gb_per_s", "wa_factor"],
            "properties": {
                "reported_mb_per_s": {
                    "type": "number",
                    "description": "Bandwidth as reported by STREAM in MB/s"
                },
                "corrected_gb_per_s": {
                    "type": "number",
                    "description": "Corrected bandwidth reflecting true hardware data movement in GB/s"
                },
                "wa_factor": {
                    "type": "number",
                    "description": "Correction factor between STREAM's and hardware byte-counting conventions"
                }
            }
        },
        "kernel_entry": {
            "type": "object",
            "required": ["name", "total_flops", "levels"],
            "properties": {
                "name": {"type": "string"},
                "total_flops": {"type": "number"},
                "levels": {
                    "type": "object",
                    "required": ["L1", "L2", "L3", "DRAM"],
                    "additionalProperties": {"$ref": "#/definitions/kernel_level"}
                }
            }
        },
        "kernel_level": {
            "type": "object",
            "required": ["arithmetic_intensity", "bound", "attainable_gflops"],
            "properties": {
                "arithmetic_intensity": {
                    "type": "number",
                    "description": "Operational intensity at this cache level (FLOP/byte)"
                },
                "bound": {
                    "type": "string",
                    "enum": ["compute", "memory"],
                    "description": "Performance bottleneck classification at this level"
                },
                "attainable_gflops": {
                    "type": "number",
                    "description": "Attainable performance in GFLOP/s at this level"
                }
            }
        }
    }
}
with open('/app/data/output_schema.json', 'w') as f:
    json.dump(schema, f, indent=4)

# ---------------------------------------------------------------------------
# STREAM benchmark C source code (v5.10)
# ---------------------------------------------------------------------------
with open('/app/data/stream.c', 'w') as f:
    f.write(r"""/*-----------------------------------------------------------------------*/
/* Program: STREAM                                                       */
/* Revision: $Id: stream.c,v 5.10 2013/01/17 16:01:06 mccalpin Exp $    */
/* Original code developed by John D. McCalpin                           */
/* Programmers: John D. McCalpin                                         */
/*              Joe R. Zagar                                             */
/*                                                                       */
/* This program measures memory transfer rates in MB/s for simple        */
/* computational kernels coded in C.                                     */
/*-----------------------------------------------------------------------*/
/* Copyright 1991-2013: John D. McCalpin                                 */
/*-----------------------------------------------------------------------*/
/* License:                                                              */
/*  1. You are free to use this program and/or to redistribute           */
/*     this program.                                                     */
/*  2. You are free to modify this program for your own use,             */
/*     including commercial use, subject to the publication              */
/*     restrictions in item 3.                                           */
/*  3. Use of this program or creation of derived works based on this    */
/*     program constitutes acceptance of these licensing restrictions.    */
/*  4. Absolutely no warranty is expressed or implied.                   */
/*-----------------------------------------------------------------------*/
# include <stdio.h>
# include <unistd.h>
# include <math.h>
# include <float.h>
# include <limits.h>
# include <sys/time.h>

/*-----------------------------------------------------------------------
 * INSTRUCTIONS:
 *
 *	1) STREAM requires different amounts of memory to run on different
 *           systems, depending on both the system cache size(s) and the
 *           granularity of the system timer.
 *     You should adjust the value of 'STREAM_ARRAY_SIZE' (below)
 *           to meet *both* of the following criteria:
 *       (a) Each array must be at least 4 times the size of the
 *           available cache memory.
 *       (b) The size should be large enough so that the 'timing calibration'
 *           output by the program is at least 20 clock-ticks.
 *
 *      Array size can be set at compile time without modifying the source
 *          code for the (many) compilers that support preprocessor definitions
 *          on the compile line.  E.g.,
 *                gcc -O -DSTREAM_ARRAY_SIZE=100000000 stream.c -o stream.100M
 */
#ifndef STREAM_ARRAY_SIZE
#   define STREAM_ARRAY_SIZE	10000000
#endif

#ifdef NTIMES
#if NTIMES<=1
#   define NTIMES	10
#endif
#endif
#ifndef NTIMES
#   define NTIMES	10
#endif

#ifndef OFFSET
#   define OFFSET	0
#endif

# define HLINE "-------------------------------------------------------------\n"

# ifndef MIN
# define MIN(x,y) ((x)<(y)?(x):(y))
# endif
# ifndef MAX
# define MAX(x,y) ((x)>(y)?(x):(y))
# endif

#ifndef STREAM_TYPE
#define STREAM_TYPE double
#endif

static STREAM_TYPE	a[STREAM_ARRAY_SIZE+OFFSET],
			b[STREAM_ARRAY_SIZE+OFFSET],
			c[STREAM_ARRAY_SIZE+OFFSET];

static double	avgtime[4] = {0}, maxtime[4] = {0},
		mintime[4] = {FLT_MAX,FLT_MAX,FLT_MAX,FLT_MAX};

static char	*label[4] = {"Copy:      ", "Scale:     ",
    "Add:       ", "Triad:     "};

static double	bytes[4] = {
    2 * sizeof(STREAM_TYPE) * STREAM_ARRAY_SIZE,
    2 * sizeof(STREAM_TYPE) * STREAM_ARRAY_SIZE,
    3 * sizeof(STREAM_TYPE) * STREAM_ARRAY_SIZE,
    3 * sizeof(STREAM_TYPE) * STREAM_ARRAY_SIZE
    };

extern double mysecond();
extern void checkSTREAMresults();
#ifdef TUNED
extern void tuned_STREAM_Copy();
extern void tuned_STREAM_Scale(STREAM_TYPE scalar);
extern void tuned_STREAM_Add();
extern void tuned_STREAM_Triad(STREAM_TYPE scalar);
#endif
#ifdef _OPENMP
extern int omp_get_num_threads();
#endif
int
main()
    {
    int			quantum, checktick();
    int			BytesPerWord;
    int			k;
    ssize_t		j;
    STREAM_TYPE		scalar;
    double		t, times[4][NTIMES];

    /* --- SETUP --- determine precision and check timing --- */

    printf(HLINE);
    printf("STREAM version $Revision: 5.10 $\n");
    printf(HLINE);
    BytesPerWord = sizeof(STREAM_TYPE);
    printf("This system uses %d bytes per array element.\n",
	BytesPerWord);

    printf(HLINE);

    printf("Array size = %llu (elements), Offset = %d (elements)\n" , (unsigned long long) STREAM_ARRAY_SIZE, OFFSET);
    printf("Memory per array = %.1f MiB (= %.1f GiB).\n",
	BytesPerWord * ( (double) STREAM_ARRAY_SIZE / 1024.0/1024.0),
	BytesPerWord * ( (double) STREAM_ARRAY_SIZE / 1024.0/1024.0/1024.0));
    printf("Total memory required = %.1f MiB (= %.1f GiB).\n",
	(3.0 * BytesPerWord) * ( (double) STREAM_ARRAY_SIZE / 1024.0/1024.),
	(3.0 * BytesPerWord) * ( (double) STREAM_ARRAY_SIZE / 1024.0/1024./1024.));
    printf("Each kernel will be executed %d times.\n", NTIMES);
    printf(" The *best* time for each kernel (excluding the first iteration)\n");
    printf(" will be used to compute the reported bandwidth.\n");

#ifdef _OPENMP
    printf(HLINE);
#pragma omp parallel
    {
#pragma omp master
	{
	    k = omp_get_num_threads();
	    printf ("Number of Threads requested = %i\n",k);
        }
    }
#endif

#ifdef _OPENMP
	k = 0;
#pragma omp parallel
#pragma omp atomic
		k++;
    printf ("Number of Threads counted = %i\n",k);
#endif

    /* Get initial value for system clock. */
#pragma omp parallel for
    for (j=0; j<STREAM_ARRAY_SIZE; j++) {
	    a[j] = 1.0;
	    b[j] = 2.0;
	    c[j] = 0.0;
	}

    printf(HLINE);

    if  ( (quantum = checktick()) >= 1)
	printf("Your clock granularity/precision appears to be "
	    "%d microseconds.\n", quantum);
    else {
	printf("Your clock granularity appears to be "
	    "less than one microsecond.\n");
	quantum = 1;
    }

    t = mysecond();
#pragma omp parallel for
    for (j = 0; j < STREAM_ARRAY_SIZE; j++)
		a[j] = 2.0E0 * a[j];
    t = 1.0E6 * (mysecond() - t);

    printf("Each test below will take on the order"
	" of %d microseconds.\n", (int) t  );
    printf("   (= %d clock ticks)\n", (int) (t/quantum) );
    printf("Increase the size of the arrays if this shows that\n");
    printf("you are not getting at least 20 clock ticks per test.\n");

    printf(HLINE);

    printf("WARNING -- The above is only a rough guideline.\n");
    printf("For best results, please be sure you know the\n");
    printf("precision of your system timer.\n");
    printf(HLINE);

    /*	--- MAIN LOOP --- repeat test cases NTIMES times --- */

    scalar = 3.0;
    for (k=0; k<NTIMES; k++)
	{
	times[0][k] = mysecond();
#ifdef TUNED
        tuned_STREAM_Copy();
#else
#pragma omp parallel for
	for (j=0; j<STREAM_ARRAY_SIZE; j++)
	    c[j] = a[j];
#endif
	times[0][k] = mysecond() - times[0][k];

	times[1][k] = mysecond();
#ifdef TUNED
        tuned_STREAM_Scale(scalar);
#else
#pragma omp parallel for
	for (j=0; j<STREAM_ARRAY_SIZE; j++)
	    b[j] = scalar*c[j];
#endif
	times[1][k] = mysecond() - times[1][k];

	times[2][k] = mysecond();
#ifdef TUNED
        tuned_STREAM_Add();
#else
#pragma omp parallel for
	for (j=0; j<STREAM_ARRAY_SIZE; j++)
	    c[j] = a[j]+b[j];
#endif
	times[2][k] = mysecond() - times[2][k];

	times[3][k] = mysecond();
#ifdef TUNED
        tuned_STREAM_Triad(scalar);
#else
#pragma omp parallel for
	for (j=0; j<STREAM_ARRAY_SIZE; j++)
	    a[j] = b[j]+scalar*c[j];
#endif
	times[3][k] = mysecond() - times[3][k];
	}

    /*	--- SUMMARY --- */

    for (k=1; k<NTIMES; k++) /* note -- skip first iteration */
	{
	for (j=0; j<4; j++)
	    {
	    avgtime[j] = avgtime[j] + times[j][k];
	    mintime[j] = MIN(mintime[j], times[j][k]);
	    maxtime[j] = MAX(maxtime[j], times[j][k]);
	    }
	}

    printf("Function    Best Rate MB/s  Avg time     Min time     Max time\n");
    for (j=0; j<4; j++) {
		avgtime[j] = avgtime[j]/(double)(NTIMES-1);

		printf("%s%12.1f  %11.6f  %11.6f  %11.6f\n", label[j],
	       1.0E-06 * bytes[j]/mintime[j],
	       avgtime[j],
	       mintime[j],
	       maxtime[j]);
    }
    printf(HLINE);

    /* --- Check Results --- */
    checkSTREAMresults();
    printf(HLINE);

    return 0;
}

# define	M	20

int
checktick()
    {
    int		i, minDelta, Delta;
    double	t1, t2, timesfound[M];

    for (i = 0; i < M; i++) {
	t1 = mysecond();
	while( ((t2=mysecond()) - t1) < 1.0E-6 )
	    ;
	timesfound[i] = t1 = t2;
	}

    minDelta = 1000000;
    for (i = 1; i < M; i++) {
	Delta = (int)( 1.0E6 * (timesfound[i]-timesfound[i-1]));
	minDelta = MIN(minDelta, MAX(Delta,0));
	}

   return(minDelta);
    }

#include <sys/time.h>

double mysecond()
{
        struct timeval tp;
        struct timezone tzp;
        int i;

        i = gettimeofday(&tp,&tzp);
        return ( (double) tp.tv_sec + (double) tp.tv_usec * 1.e-6 );
}

#ifndef abs
#define abs(a) ((a) >= 0 ? (a) : -(a))
#endif
void checkSTREAMresults ()
{
	STREAM_TYPE aj,bj,cj,scalar;
	STREAM_TYPE aSumErr,bSumErr,cSumErr;
	STREAM_TYPE aAvgErr,bAvgErr,cAvgErr;
	double epsilon;
	ssize_t	j;
	int	k,ierr,err;

    /* reproduce initialization */
	aj = 1.0;
	bj = 2.0;
	cj = 0.0;
    /* a[] is modified during timing check */
	aj = 2.0E0 * aj;
    /* now execute timing loop */
	scalar = 3.0;
	for (k=0; k<NTIMES; k++)
        {
            cj = aj;
            bj = scalar*cj;
            cj = aj+bj;
            aj = bj+scalar*cj;
        }

	/* accumulate deltas between observed and expected results */
	aSumErr = 0.0;
	bSumErr = 0.0;
	cSumErr = 0.0;
	for (j=0; j<STREAM_ARRAY_SIZE; j++) {
		aSumErr += abs(a[j] - aj);
		bSumErr += abs(b[j] - bj);
		cSumErr += abs(c[j] - cj);
	}
	aAvgErr = aSumErr / (STREAM_TYPE) STREAM_ARRAY_SIZE;
	bAvgErr = bSumErr / (STREAM_TYPE) STREAM_ARRAY_SIZE;
	cAvgErr = cSumErr / (STREAM_TYPE) STREAM_ARRAY_SIZE;

	if (sizeof(STREAM_TYPE) == 4) {
		epsilon = 1.e-6;
	}
	else if (sizeof(STREAM_TYPE) == 8) {
		epsilon = 1.e-13;
	}
	else {
		printf("WEIRD: sizeof(STREAM_TYPE) = %lu\n",sizeof(STREAM_TYPE));
        epsilon = 1.e-6;
	}

	err = 0;
	if (abs(aAvgErr/aj) > epsilon) {
		err++;
		printf ("Failed Validation on array a[], AvgRelAbsErr=%e\n",abs(aAvgErr));
		printf ("     Expected Value: %e, AvgAbsErr: %e, MaxRelErr: %e\n",aj,aAvgErr,aAvgErr);
	}
	if (abs(bAvgErr/bj) > epsilon) {
		err++;
		printf ("Failed Validation on array b[], AvgRelAbsErr=%e\n",abs(bAvgErr));
		printf ("     Expected Value: %e, AvgAbsErr: %e, MaxRelErr: %e\n",bj,bAvgErr,bAvgErr);
	}
	if (abs(cAvgErr/cj) > epsilon) {
		err++;
		printf ("Failed Validation on array c[], AvgRelAbsErr=%e\n",abs(cAvgErr));
		printf ("     Expected Value: %e, AvgAbsErr: %e, MaxRelErr: %e\n",cj,cAvgErr,cAvgErr);
	}
	if (err == 0) {
		printf ("Solution Validates: avg error less than %e on all three arrays\n",epsilon);
	}
}
""")

print("All task data files generated successfully in /app/data/")
for name in sorted(os.listdir('/app/data')):
    path = os.path.join('/app/data', name)
    size = os.path.getsize(path)
    print(f"  {name}: {size} bytes")
