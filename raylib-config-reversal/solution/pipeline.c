/*
 * pipeline.c - Headless image processing pipeline using raylib
 *
 * Loads test.png, applies a chain of image transformations,
 * exports the result and writes a pixel report.
 *
 * Compile:
 *   gcc pipeline.c -I/app/target -L/app/target -lraylib \
 *       -lGL -lm -lpthread -ldl -lrt -lX11 -o /app/pipeline
 */

#include "raylib.h"
#include <stdio.h>
#include <stdlib.h>

int main(void)
{
    /* Step 1: Load input image */
    Image img = LoadImage("/app/input/test.png");
    if (!IsImageValid(img)) {
        fprintf(stderr, "ERROR: Failed to load /app/input/test.png\n");
        return 1;
    }

    /* Step 2: Convert to grayscale */
    ImageColorGrayscale(&img);

    /* Step 3: Apply 3x3 Gaussian blur kernel (pre-normalized) */
    float kernel[] = {
        0.0625f, 0.125f, 0.0625f,
        0.125f,  0.25f,  0.125f,
        0.0625f, 0.125f, 0.0625f
    };
    ImageKernelConvolution(&img, kernel, 9);

    /* Step 4: Crop to center 100x100 */
    ImageCrop(&img, (Rectangle){ 50.0f, 50.0f, 100.0f, 100.0f });

    /* Step 5: Flip vertically */
    ImageFlipVertical(&img);

    /* Step 6: Adjust brightness +40 */
    ImageColorBrightness(&img, 40);

    /* Step 7: Export result */
    ExportImage(img, "/app/output/result.png");

    /* Step 8: Read pixel values and write report */
    int coords[][2] = { {25, 25}, {75, 25}, {25, 75}, {75, 75} };
    FILE *fp = fopen("/app/output/report.txt", "w");
    if (!fp) {
        fprintf(stderr, "ERROR: Failed to open report.txt for writing\n");
        UnloadImage(img);
        return 1;
    }

    fprintf(fp, "DIMENSIONS: %d %d\n", img.width, img.height);

    for (int i = 0; i < 4; i++) {
        Color c = GetImageColor(img, coords[i][0], coords[i][1]);
        fprintf(fp, "PIXEL %d %d: %d %d %d %d\n",
                coords[i][0], coords[i][1], c.r, c.g, c.b, c.a);
    }

    fclose(fp);
    UnloadImage(img);

    printf("Pipeline complete. Output at /app/output/\n");
    return 0;
}
