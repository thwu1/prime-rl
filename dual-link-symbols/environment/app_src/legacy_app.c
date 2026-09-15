#include "processor_v2.h"
#include <stdio.h>
#include <stdlib.h>

int main(int argc, char *argv[]) {
    const char *input = "/app/test_data.csv";
    const char *output = "/app/output.txt";

    if (proc_init(1) != 0) {
        fprintf(stderr, "Failed to initialize processor\n");
        return 1;
    }

    proc_record records[100];
    int count = proc_load(input, records, 100);
    if (count <= 0) {
        fprintf(stderr, "Failed to load data from %s\n", input);
        return 1;
    }

    FILE *fp = fopen(output, "w");
    if (!fp) {
        fprintf(stderr, "Cannot open %s for writing\n", output);
        return 1;
    }

    double sum = proc_compute(records, count, 0);
    double mean = proc_compute(records, count, 1);
    double max_val = proc_compute(records, count, 2);
    double min_val = proc_compute(records, count, 3);

    fprintf(fp, "RECORDS: %d\n", count);
    fprintf(fp, "SUM: %s\n", proc_format(sum, 4));
    fprintf(fp, "MEAN: %s\n", proc_format(mean, 4));
    fprintf(fp, "MAX: %s\n", proc_format(max_val, 4));
    fprintf(fp, "MIN: %s\n", proc_format(min_val, 4));

    /* Compute filtered sum for records with type > 2 */
    double filtered_sum = 0.0;
    int filtered_count = 0;
    for (int i = 0; i < count; i++) {
        if (records[i].type > 2) {
            filtered_sum += records[i].value;
            filtered_count++;
        }
    }
    fprintf(fp, "FILTERED_SUM(type>2): %s (%d records)\n",
            proc_format(filtered_sum, 4), filtered_count);

    /* List labels of flagged records */
    fprintf(fp, "FLAGGED:");
    for (int i = 0; i < count; i++) {
        if (records[i].flags & 1) {
            fprintf(fp, " %s", records[i].label);
        }
    }
    fprintf(fp, "\n");

    fclose(fp);
    proc_cleanup();

    printf("Processing complete. Results written to %s\n", output);
    return 0;
}
