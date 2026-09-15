# Build Specification: Raylib Configuration Analysis & Image Pipeline

## Objective

You are given a pre-compiled raylib static library at `/app/target/libraylib.a` that was
built with a **customized `config.h`**. Some modules and features have been deliberately
disabled compared to the default raylib configuration.

Your task has two parts:

### Part 1: Configuration Reverse-Engineering

Analyze the target library to determine exactly which `config.h` flags differ from the
defaults. The original (unmodified) raylib source is available at `/app/raylib/` for
reference. You must produce a JSON report at `/app/analysis/config_report.json`.

The report must contain a JSON object where keys are config flag names and values are
booleans (`true` = enabled, `false` = disabled). You must report the status of at least
these flags:

- `SUPPORT_MODULE_RSHAPES`
- `SUPPORT_MODULE_RTEXTURES`
- `SUPPORT_MODULE_RTEXT`
- `SUPPORT_MODULE_RMODELS`
- `SUPPORT_MODULE_RAUDIO`
- `SUPPORT_CAMERA_SYSTEM`
- `SUPPORT_GESTURES_SYSTEM`
- `SUPPORT_RPRAND_GENERATOR`
- `SUPPORT_SCREEN_CAPTURE`
- `SUPPORT_AUTOMATION_EVENTS`
- `SUPPORT_COMPRESSION_API`
- `SUPPORT_IMAGE_EXPORT`
- `SUPPORT_IMAGE_GENERATION`

### Part 2: Headless Image Processing Pipeline

Using **only** the functions available in the target library (`/app/target/libraylib.a`),
write a C program that performs the following image processing pipeline:

1. Load `/app/input/test.png` (a 200x200 RGBA image with 4 colored quadrants)
2. Convert to grayscale (`ImageColorGrayscale`)
3. Apply a 3x3 Gaussian blur kernel using `ImageKernelConvolution`:
   - Kernel (pre-normalized): `{0.0625, 0.125, 0.0625, 0.125, 0.25, 0.125, 0.0625, 0.125, 0.0625}`
4. Crop to center 100x100: `ImageCrop` with rectangle `{50, 50, 100, 100}`
5. Flip vertically: `ImageFlipVertical`
6. Adjust brightness by +40: `ImageColorBrightness`
7. Export result to `/app/output/result.png`

Additionally, read pixel values from the processed image using `GetImageColor` and write
a report to `/app/output/report.txt` with the format:
```
DIMENSIONS: <width> <height>
PIXEL 25 25: <r> <g> <b> <a>
PIXEL 75 25: <r> <g> <b> <a>
PIXEL 25 75: <r> <g> <b> <a>
PIXEL 75 75: <r> <g> <b> <a>
```

### Deliverables

Place all output at the following paths:
- `/app/analysis/config_report.json` — Configuration analysis (Part 1)
- `/app/output/result.png` — Processed image (Part 2)
- `/app/output/report.txt` — Pixel report (Part 2)
- `/app/pipeline` — Compiled pipeline binary (Part 2)

### Available Resources

- `/app/raylib/` — Full unmodified raylib source (for reference)
- `/app/target/libraylib.a` — Pre-built target library (link against this)
- `/app/target/raylib.h` — Header file (include this)
- `/app/target/raymath.h` — Math header
- `/app/target/rlgl.h` — OpenGL abstraction header
- `/app/input/test.png` — Input image for processing
