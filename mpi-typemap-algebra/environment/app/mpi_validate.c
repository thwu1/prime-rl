/*
 * MPI Derived Datatype Validation Program
 *
 * Creates the same MPI datatypes defined in type_defs.json using the
 * actual OpenMPI library and queries their properties (lb, ub, extent,
 * true_lb, true_ub, true_extent, size) via the MPI API.
 *
 * Outputs ground truth as JSON to /app/mpi_ground_truth.json.
 */

#include <mpi.h>
#include <stdio.h>
#include <stdlib.h>

static void write_type(FILE *fp, const char *name, MPI_Datatype dt, int last) {
    int size;
    MPI_Aint lb, extent, true_lb, true_extent;
    MPI_Type_size(dt, &size);
    MPI_Type_get_extent(dt, &lb, &extent);
    MPI_Type_get_true_extent(dt, &true_lb, &true_extent);
    fprintf(fp, "  \"%s\": {\"lb\": %ld, \"ub\": %ld, \"extent\": %ld, "
            "\"true_lb\": %ld, \"true_ub\": %ld, \"true_extent\": %ld, "
            "\"size\": %d}%s\n",
            name, (long)lb, (long)(lb + extent), (long)extent,
            (long)true_lb, (long)(true_lb + true_extent), (long)true_extent,
            size, last ? "" : ",");
}

int main(int argc, char **argv) {
    MPI_Init(&argc, &argv);

    /* particle_pos: struct [3 MPI_DOUBLE at 0, 1 MPI_INT at 24] */
    MPI_Datatype particle_pos;
    {
        int bl[] = {3, 1};
        MPI_Aint disp[] = {0, 24};
        MPI_Datatype types[] = {MPI_DOUBLE, MPI_INT};
        MPI_Type_create_struct(2, bl, disp, types, &particle_pos);
        MPI_Type_commit(&particle_pos);
    }

    /* strided_doubles: vector(count=4, blocklength=2, stride=5, MPI_DOUBLE) */
    MPI_Datatype strided_doubles;
    MPI_Type_vector(4, 2, 5, MPI_DOUBLE, &strided_doubles);
    MPI_Type_commit(&strided_doubles);

    /* padded_particle: resized(particle_pos, lb=0, extent=64) */
    MPI_Datatype padded_particle;
    MPI_Type_create_resized(particle_pos, 0, 64, &padded_particle);
    MPI_Type_commit(&padded_particle);

    /* particle_array: contiguous(3, padded_particle) */
    MPI_Datatype particle_array;
    MPI_Type_contiguous(3, padded_particle, &particle_array);
    MPI_Type_commit(&particle_array);

    /* column_slice: subarray(ndims=2, sizes=[6,8], subsizes=[3,2],
       starts=[1,3], order=C, MPI_DOUBLE) */
    MPI_Datatype column_slice;
    {
        int sizes[] = {6, 8};
        int subsizes[] = {3, 2};
        int starts[] = {1, 3};
        MPI_Type_create_subarray(2, sizes, subsizes, starts,
                                 MPI_ORDER_C, MPI_DOUBLE, &column_slice);
        MPI_Type_commit(&column_slice);
    }

    /* scattered_ints: hindexed_block(blocklength=2,
       displacements=[0,20,52,100], MPI_INT) */
    MPI_Datatype scattered_ints;
    {
        MPI_Aint disp[] = {0, 20, 52, 100};
        MPI_Type_create_hindexed_block(4, 2, disp, MPI_INT, &scattered_ints);
        MPI_Type_commit(&scattered_ints);
    }

    /* mixed_struct: struct [1 MPI_CHAR at 0, 2 MPI_DOUBLE at 4,
       1 MPI_SHORT at 20] */
    MPI_Datatype mixed_struct;
    {
        int bl[] = {1, 2, 1};
        MPI_Aint disp[] = {0, 4, 20};
        MPI_Datatype types[] = {MPI_CHAR, MPI_DOUBLE, MPI_SHORT};
        MPI_Type_create_struct(3, bl, disp, types, &mixed_struct);
        MPI_Type_commit(&mixed_struct);
    }

    /* nested_vector: vector(count=3, blocklength=1, stride=2, particle_pos) */
    MPI_Datatype nested_vector;
    MPI_Type_vector(3, 1, 2, particle_pos, &nested_vector);
    MPI_Type_commit(&nested_vector);

    /* Write ground truth JSON */
    const char *outpath = "/app/mpi_ground_truth.json";
    FILE *fp = fopen(outpath, "w");
    if (!fp) {
        fprintf(stderr, "Error: cannot open %s for writing\n", outpath);
        MPI_Finalize();
        return 1;
    }

    fprintf(fp, "{\n");
    write_type(fp, "particle_pos", particle_pos, 0);
    write_type(fp, "strided_doubles", strided_doubles, 0);
    write_type(fp, "padded_particle", padded_particle, 0);
    write_type(fp, "particle_array", particle_array, 0);
    write_type(fp, "column_slice", column_slice, 0);
    write_type(fp, "scattered_ints", scattered_ints, 0);
    write_type(fp, "mixed_struct", mixed_struct, 0);
    write_type(fp, "nested_vector", nested_vector, 1);
    fprintf(fp, "}\n");
    fclose(fp);

    printf("Ground truth written to %s\n", outpath);

    MPI_Type_free(&nested_vector);
    MPI_Type_free(&mixed_struct);
    MPI_Type_free(&scattered_ints);
    MPI_Type_free(&column_slice);
    MPI_Type_free(&particle_array);
    MPI_Type_free(&padded_particle);
    MPI_Type_free(&strided_doubles);
    MPI_Type_free(&particle_pos);

    MPI_Finalize();
    return 0;
}
