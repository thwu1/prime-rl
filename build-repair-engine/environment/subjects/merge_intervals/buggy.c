#include <stdlib.h>
#include <string.h>

typedef struct {
    int start;
    int end;
} Interval;

static int cmp_intervals(const void *a, const void *b) {
    const Interval *ia = (const Interval *)a;
    const Interval *ib = (const Interval *)b;
    if (ia->start != ib->start)
        return ia->start - ib->start;
    return ia->end - ib->end;
}

int total_span(const Interval *intervals, int n) {
    int total = 0;
    for (int i = 0; i < n; i++) {
        total += intervals[i].end - intervals[i].start;
    }
    return total;
}

int point_in_intervals(const Interval *intervals, int n, int pt) {
    for (int i = 0; i < n; i++) {
        if (pt >= intervals[i].start && pt < intervals[i].end)
            return 1;
    }
    return 0;
}

int merge_intervals(Interval *in, int n, Interval *out) {
    if (n <= 0) return 0;

    qsort(in, n, sizeof(Interval), cmp_intervals);

    out[0] = in[0];
    int count = 1;

    for (int i = 1; i < n; i++) {
        if (in[i].start < out[count - 1].end) {
            if (in[i].end > out[count - 1].end)
                out[count - 1].end = in[i].end;
        } else {
            out[count] = in[i];
            count++;
        }
    }

    return count;
}
