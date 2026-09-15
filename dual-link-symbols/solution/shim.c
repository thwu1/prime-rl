/*
 *
 * Binary compatibility shim: exports v2 API symbols and translates
 * calls to the v5 processor library internally.
 */
#include "processor.h"
#include <stdlib.h>
#include <string.h>

/* v2 struct layout — must match the original libprocessor v2 ABI exactly.
 * Fields are in a different order than v5's proc_record_v5:
 *   v2: {int type, int flags, double value, char label[32]}  = 48 bytes
 *   v5: {int type, [pad], double value, char label[64], int flags, int priority} = 88 bytes
 */
typedef struct {
    int type;
    int flags;
    double value;
    char label[32];
} proc_record_v2;

/* Convert an array of v2 records to v5 format. Caller must free the result. */
static proc_record_v5 *v2_to_v5(const proc_record_v2 *v2, int count) {
    proc_record_v5 *v5 = calloc(count, sizeof(proc_record_v5));
    if (!v5) return NULL;
    for (int i = 0; i < count; i++) {
        v5[i].type = v2[i].type;
        v5[i].value = v2[i].value;
        v5[i].flags = v2[i].flags;
        strncpy(v5[i].label, v2[i].label, 63);
        v5[i].label[63] = '\0';
        v5[i].priority = 0;
    }
    return v5;
}

/* Convert an array of v5 records to v2 format, writing into caller's buffer. */
static void v5_to_v2(proc_record_v2 *v2, const proc_record_v5 *v5, int count) {
    for (int i = 0; i < count; i++) {
        v2[i].type = v5[i].type;
        v2[i].flags = v5[i].flags;
        v2[i].value = v5[i].value;
        strncpy(v2[i].label, v5[i].label, 31);
        v2[i].label[31] = '\0';
    }
}

/* --- v2 API shim functions --- */

int proc_init(int mode) {
    /* v5 added a verbose parameter; pass 0 for silent operation */
    return processor_initialize(mode, 0);
}

int proc_load(const char *filename, proc_record_v2 *records, int max_records) {
    /* v5 changed return semantics: returns 0 on success with count via
     * output parameter, whereas v2 returns the count directly. */
    proc_record_v5 *v5_records = calloc(max_records, sizeof(proc_record_v5));
    if (!v5_records) return -1;

    int actual_count = 0;
    int ret = processor_load_file(filename, v5_records, max_records, &actual_count);
    if (ret != 0) {
        free(v5_records);
        return -1;
    }

    /* Convert loaded v5 records into the caller's v2 record buffer */
    v5_to_v2(records, v5_records, actual_count);
    free(v5_records);

    return actual_count;  /* v2 returns count, not status */
}

double proc_compute(proc_record_v2 *records, int count, int operation) {
    /* Convert v2 records to v5 layout for the v5 compute function */
    proc_record_v5 *v5_records = v2_to_v5(records, count);
    if (!v5_records) return 0.0;

    double result = processor_compute(v5_records, count, operation);
    free(v5_records);
    return result;
}

char *proc_format(double result, int precision) {
    /* v5 added a scientific-notation flag; pass 0 for decimal format */
    return processor_format_result(result, precision, 0);
}

void proc_cleanup(void) {
    processor_shutdown();
}
