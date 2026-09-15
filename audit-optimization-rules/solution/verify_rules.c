
#include <stdio.h>
#include <stdint.h>

static uint32_t vals[] = {
    0, 1, 2, 3, 5, 7, 15, 0xFFu, 0x100u, 0x1234u,
    0x7FFFu, 0x8000u, 0xFFFFu, 0x7FFFFFFFu, 0x80000000u,
    0x80000001u, 0xC0000000u, 0xFFFFFFFEu, 0xFFFFFFFFu
};
#define NV (sizeof(vals)/sizeof(vals[0]))

static uint32_t nvals[] = {1, 2, 3, 4, 7, 8, 15, 16, 17, 24, 31};
#define NN (sizeof(nvals)/sizeof(nvals[0]))

typedef struct {
    int found;
    uint32_t a, b, n;
    int has_b, has_n;
} Result;

int main(void)
{
    Result r[12];
    int i, j, k;

    for (i = 0; i < 12; i++) {
        r[i].found = 0;
        r[i].a = r[i].b = r[i].n = 0;
        r[i].has_b = 1; r[i].has_n = 0;
    }
    r[5].has_b = 0; r[5].has_n = 1;   /* Rule 6: uses a, n */
    r[10].has_b = 0; r[10].has_n = 0;  /* Rule 11: uses only a */

    /* Rule 1: (a != b) & ((a | b) == 0) == 0 */
    for (i = 0; i < (int)NV && !r[0].found; i++)
        for (j = 0; j < (int)NV && !r[0].found; j++) {
            uint32_t a = vals[i], b = vals[j];
            if (((a != b) & ((a | b) == 0)) != 0u)
            { r[0].found = 1; r[0].a = a; r[0].b = b; }
        }

    /* Rule 2: (a == b) | ((a & b) != a) == 1 */
    for (i = 0; i < (int)NV && !r[1].found; i++)
        for (j = 0; j < (int)NV && !r[1].found; j++) {
            uint32_t a = vals[i], b = vals[j];
            if (((a == b) | ((a & b) != a)) != 1u)
            { r[1].found = 1; r[1].a = a; r[1].b = b; }
        }

    /* Rule 3: (a | b) - (a & b) == a ^ b */
    for (i = 0; i < (int)NV && !r[2].found; i++)
        for (j = 0; j < (int)NV && !r[2].found; j++) {
            uint32_t a = vals[i], b = vals[j];
            if (((a | b) - (a & b)) != (a ^ b))
            { r[2].found = 1; r[2].a = a; r[2].b = b; }
        }

    /* Rule 4: (a + b) ^ (a ^ b) == (a & b) << 1 */
    for (i = 0; i < (int)NV && !r[3].found; i++)
        for (j = 0; j < (int)NV && !r[3].found; j++) {
            uint32_t a = vals[i], b = vals[j];
            if (((a + b) ^ (a ^ b)) != ((a & b) << 1))
            { r[3].found = 1; r[3].a = a; r[3].b = b; }
        }

    /* Rule 5: ~(a & b) & (a | b) == a ^ b */
    for (i = 0; i < (int)NV && !r[4].found; i++)
        for (j = 0; j < (int)NV && !r[4].found; j++) {
            uint32_t a = vals[i], b = vals[j];
            if (((~(a & b)) & (a | b)) != (a ^ b))
            { r[4].found = 1; r[4].a = a; r[4].b = b; }
        }

    /* Rule 6: (a << n) >> n == a  for 0 < n < 32 */
    for (i = 0; i < (int)NV && !r[5].found; i++)
        for (k = 0; k < (int)NN && !r[5].found; k++) {
            uint32_t a = vals[i], n = nvals[k];
            if (((a << n) >> n) != a)
            { r[5].found = 1; r[5].a = a; r[5].n = n; }
        }

    /* Rule 7: (a ^ b) | (a & b) == a | b */
    for (i = 0; i < (int)NV && !r[6].found; i++)
        for (j = 0; j < (int)NV && !r[6].found; j++) {
            uint32_t a = vals[i], b = vals[j];
            if (((a ^ b) | (a & b)) != (a | b))
            { r[6].found = 1; r[6].a = a; r[6].b = b; }
        }

    /* Rule 8: (a & ~b) | (~a & b) == ~(a ^ b) */
    for (i = 0; i < (int)NV && !r[7].found; i++)
        for (j = 0; j < (int)NV && !r[7].found; j++) {
            uint32_t a = vals[i], b = vals[j];
            if (((a & ~b) | (~a & b)) != (~(a ^ b)))
            { r[7].found = 1; r[7].a = a; r[7].b = b; }
        }

    /* Rule 9: (a + b) * (a - b) == a*a - b*b */
    for (i = 0; i < (int)NV && !r[8].found; i++)
        for (j = 0; j < (int)NV && !r[8].found; j++) {
            uint32_t a = vals[i], b = vals[j];
            if (((a + b) * (a - b)) != (a * a - b * b))
            { r[8].found = 1; r[8].a = a; r[8].b = b; }
        }

    /* Rule 10: (a >> 1) + (b >> 1) + ((a | b) & 1) == (a + b) >> 1 */
    for (i = 0; i < (int)NV && !r[9].found; i++)
        for (j = 0; j < (int)NV && !r[9].found; j++) {
            uint32_t a = vals[i], b = vals[j];
            if (((a >> 1) + (b >> 1) + ((a | b) & 1)) != ((a + b) >> 1))
            { r[9].found = 1; r[9].a = a; r[9].b = b; }
        }

    /* Rule 11: a ^ 0xFFFFFFFFu == ~a */
    for (i = 0; i < (int)NV && !r[10].found; i++) {
        uint32_t a = vals[i];
        if ((a ^ 0xFFFFFFFFu) != (~a))
        { r[10].found = 1; r[10].a = a; }
    }

    /* Rule 12: (a * b) / b == a  when b != 0 */
    for (i = 0; i < (int)NV && !r[11].found; i++)
        for (j = 0; j < (int)NV && !r[11].found; j++) {
            uint32_t a = vals[i], b = vals[j];
            if (b == 0) continue;
            if ((a * b) / b != a)
            { r[11].found = 1; r[11].a = a; r[11].b = b; }
        }

    /* Output JSON */
    printf("{\n");
    for (i = 0; i < 12; i++) {
        printf("  \"rule_%d\": ", i + 1);
        if (r[i].found) {
            printf("{\"correct\": false, \"counterexample\": {\"a\": %u", r[i].a);
            if (r[i].has_b)
                printf(", \"b\": %u", r[i].b);
            if (r[i].has_n)
                printf(", \"n\": %u", r[i].n);
            printf("}}");
        } else {
            printf("{\"correct\": true}");
        }
        if (i < 11) printf(",");
        printf("\n");
    }
    printf("}\n");
    return 0;
}
