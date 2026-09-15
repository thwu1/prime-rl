#ifndef PROCESSOR_H
#define PROCESSOR_H

/* libprocessor v5 API
 * Data processing library - current version.
 * Significant API changes from v2: renamed functions, altered signatures,
 * restructured record layout, changed return semantics.
 */

typedef struct {
    int type;
    double value;
    char label[64];
    int flags;
    int priority;
} proc_record_v5;

/* Initialize the processor with mode and verbosity.
 * Returns 0 on success, -1 on error. */
int processor_initialize(int mode, int verbose);

/* Load records from a CSV file.
 * Returns 0 on success with count written to *actual_count, or -1 on error. */
int processor_load_file(const char *filename, proc_record_v5 *records,
                        int max_records, int *actual_count);

/* Compute an aggregate over records.
 * Operations: 0=SUM, 1=MEAN, 2=MAX, 3=MIN. Returns NAN for unknown ops. */
double processor_compute(proc_record_v5 *records, int count, int operation);

/* Apply a transform to record values in-place.
 * Transforms: 0=ABS, 1=SQRT, 2=LOG. Returns 0 on success. */
int processor_transform(proc_record_v5 *records, int count, int transform_type);

/* Format a result value with given precision.
 * If scientific != 0, uses scientific notation.
 * Returns pointer to an internal static buffer. */
char *processor_format_result(double result, int precision, int scientific);

/* Shut down the processor and release resources. */
void processor_shutdown(void);

#endif
