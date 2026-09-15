#include "processor_v2.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int initialized = 0;
static int proc_mode = 0;

int proc_init(int mode) {
    proc_mode = mode;
    initialized = 1;
    return 0;
}

int proc_load(const char *filename, proc_record *records, int max_records) {
    FILE *fp = fopen(filename, "r");
    if (!fp) return -1;

    int count = 0;
    char line[256];
    while (fgets(line, sizeof(line), fp) && count < max_records) {
        if (line[0] == '#' || line[0] == '\n') continue;
        proc_record *r = &records[count];
        char label[32];
        if (sscanf(line, "%d,%d,%lf,%31s", &r->type, &r->flags, &r->value, label) == 4) {
            strncpy(r->label, label, 31);
            r->label[31] = '\0';
            count++;
        }
    }
    fclose(fp);
    return count;
}

double proc_compute(proc_record *records, int count, int operation) {
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
    }
    return result;
}

static char fmt_buf[64];

char *proc_format(double result, int precision) {
    snprintf(fmt_buf, sizeof(fmt_buf), "%.*f", precision, result);
    return fmt_buf;
}

void proc_cleanup(void) {
    initialized = 0;
}
