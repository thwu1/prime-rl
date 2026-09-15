#ifndef PROCESSOR_V2_H
#define PROCESSOR_V2_H

/* libprocessor v2 API
 * Data processing library - discontinued, no longer maintained.
 * This header defines the v2 interface that legacy_app was compiled against.
 */

typedef struct {
    int type;
    int flags;
    double value;
    char label[32];
} proc_record;

/* Initialize the processor. Returns 0 on success, -1 on error. */
int proc_init(int mode);

/* Load records from a CSV file into the records array.
 * CSV format: type,flags,value,label (lines starting with '#' are skipped).
 * Returns number of records loaded on success, or -1 on error. */
int proc_load(const char *filename, proc_record *records, int max_records);

/* Compute an aggregate over records.
 * Operations: 0=SUM, 1=MEAN, 2=MAX, 3=MIN */
double proc_compute(proc_record *records, int count, int operation);

/* Format a double value with the given decimal precision.
 * Returns pointer to an internal static buffer (overwritten on next call). */
char *proc_format(double result, int precision);

/* Release any resources held by the processor. */
void proc_cleanup(void);

#endif
