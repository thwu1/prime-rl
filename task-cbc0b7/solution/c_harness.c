
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <math.h>

/*
 * Standalone verification harness: extracts core LED algorithms from
 * the C firmware source and exercises them without ESP-IDF dependencies.
 */

/* Wave brightness table extracted from c_ubt_led.c */
static uint8_t wave[] = {
    0,   16,  31,  47,  63,  78,  93,  108, 122, 136, 149, 162, 174,
    185, 196, 206, 215, 223, 230, 237, 242, 246, 250, 252, 254, 255,
    254, 252, 250, 246, 242, 237, 230, 223, 215, 206, 196, 185, 174,
    162, 149, 136, 122, 108, 93,  78,  63,  47,  31,  16,  0,
};
static const int wave_len = sizeof(wave) / sizeof(wave[0]);

/*
 * Color preprocessing from ws_commands.c:
 *   hue = (int)(h > 0 ? h : 360 + h)
 *   saturation = (int)(s * 255)
 *   value = (int)(v * 255)
 */
static void preprocess_hsv(double h_in, double s_in, double v_in,
                           int *hue, int *sat, int *val)
{
    *hue = (int)(h_in > 0 ? h_in : 360 + h_in);
    *sat = (int)(s_in * 255);
    *val = (int)(v_in * 255);
}

/*
 * Standard HSV-to-RGB conversion matching ESP-IDF's led_strip_set_pixel_hsv.
 * Input: hue (integer degrees), sat/val (0-255).
 * Output: r, g, b (0-255).
 */
static void hsv_to_rgb(int hue, int sat, int val, int *r, int *g, int *b)
{
    /* Normalize hue to [0, 360) */
    hue = ((hue % 360) + 360) % 360;

    double s_norm = sat / 255.0;
    double v_norm = val / 255.0;
    double c = v_norm * s_norm;
    double x = c * (1.0 - fabs(fmod((double)hue / 60.0, 2.0) - 1.0));
    double m = v_norm - c;
    double r_t, g_t, b_t;

    if (hue < 60)       { r_t = c; g_t = x; b_t = 0; }
    else if (hue < 120) { r_t = x; g_t = c; b_t = 0; }
    else if (hue < 180) { r_t = 0; g_t = c; b_t = x; }
    else if (hue < 240) { r_t = 0; g_t = x; b_t = c; }
    else if (hue < 300) { r_t = x; g_t = 0; b_t = c; }
    else                { r_t = c; g_t = 0; b_t = x; }

    *r = (int)((r_t + m) * 255.0);
    *g = (int)((g_t + m) * 255.0);
    *b = (int)((b_t + m) * 255.0);
}

int main(void)
{
    int i;

    /* Output wave table */
    printf("{\"wave_table\":[");
    for (i = 0; i < wave_len; i++) {
        if (i) printf(",");
        printf("%d", wave[i]);
    }
    printf("],\"wave_table_length\":%d,\"hsv_tests\":[", wave_len);

    /* HSV test inputs */
    double tests[][3] = {
        {0.0,    1.0, 1.0},
        {120.0,  1.0, 1.0},
        {240.0,  1.0, 1.0},
        {0.0,    0.0, 1.0},
        {0.0,    0.0, 0.0},
        {0.0,    0.5, 1.0},
        {-60.0,  1.0, 1.0},
        {720.0,  1.0, 1.0}
    };
    int n = sizeof(tests) / sizeof(tests[0]);

    for (i = 0; i < n; i++) {
        int hue, sat, val, r, g, b;
        preprocess_hsv(tests[i][0], tests[i][1], tests[i][2], &hue, &sat, &val);
        hsv_to_rgb(hue, sat, val, &r, &g, &b);
        if (i) printf(",");
        printf("{\"h\":%.1f,\"s\":%.1f,\"v\":%.1f,\"r\":%d,\"g\":%d,\"b\":%d}",
               tests[i][0], tests[i][1], tests[i][2], r, g, b);
    }

    printf("]}\n");
    return 0;
}
