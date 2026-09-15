#include "processor.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

static int initialized = 0;
static int verbose_mode = 0;
static int init_mode = 0;

int processor_initialize(int mode, int verbose) {
    init_mode = mode;
    verbose_mode = verbose;
    initialized = 1;
    if (verbose) printf("[processor] Initialized with mode=%d\n", mode);
    return 0;
}

int processor_load_file(const char *filename, proc_record_v5 *records,
                        int max_records, int *actual_count) {
    FILE *fp = fopen(filename, "r");
    if (!fp) return -1;

    int count = 0;
    char line[256];
    while (fgets(line, sizeof(line), fp) && count < max_records) {
        if (line[0] == '#' || line[0] == '\n') continue;
        proc_record_v5 *r = &records[count];
        char label[64];
        if (sscanf(line, "%d,%d,%lf,%63s",
                   &r->type, &r->flags, &r->value, label) == 4) {
            strncpy(r->label, label, 63);
            r->label[63] = '\0';
            r->priority = 0;
            count++;
        }
    }
    fclose(fp);
    if (actual_count) *actual_count = count;
    return 0;
}

double processor_compute(proc_record_v5 *records, int count, int operation) {
    if (count <= 0) return 0.0;
    double result = 0.0;
    switch (operation) {
        case 0: /* SUM */
            for (int i = 0; i < count; i++) result += records[i].value;
            break;
        case 1: /* MEAN */
            for (int i = 0; i < count; i++) result += records[i].value;
            result /= count;
            break;
        case 2: /* MAX */
            result = records[0].value;
            for (int i = 1; i < count; i++)
                if (records[i].value > result) result = records[i].value;
            break;
        case 3: /* MIN */
            result = records[0].value;
            for (int i = 1; i < count; i++)
                if (records[i].value < result) result = records[i].value;
            break;
        default:
            return NAN;
    }
    return result;
}

int processor_transform(proc_record_v5 *records, int count, int transform_type) {
    for (int i = 0; i < count; i++) {
        switch (transform_type) {
            case 0: records[i].value = fabs(records[i].value); break;
            case 1: records[i].value = sqrt(fabs(records[i].value)); break;
            case 2: records[i].value = log(fabs(records[i].value) + 1.0); break;
            default: return -1;
        }
    }
    return 0;
}

static char fmt_buf[128];

char *processor_format_result(double result, int precision, int scientific) {
    if (scientific) {
        snprintf(fmt_buf, sizeof(fmt_buf), "%.*e", precision, result);
    } else {
        snprintf(fmt_buf, sizeof(fmt_buf), "%.*f", precision, result);
    }
    return fmt_buf;
}

void processor_shutdown(void) {
    initialized = 0;
    verbose_mode = 0;
}
