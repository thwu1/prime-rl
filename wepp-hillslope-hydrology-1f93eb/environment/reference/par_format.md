# CLIGEN Station Parameter File (.PAR) Format

CLIGEN `.PAR` files store monthly climate statistics for US weather stations
using Fortran fixed-width I/O conventions. Each station record consists of
82 data lines followed by optional interpolation metadata.

All lines containing monthly data have 12 values (January through December).

## Header (Lines 1-3)

**Line 1** — Station identification
`FORMAT(A41,I2,I4,I2)`
- Columns 1-41: Station name (character string, may include leading/trailing spaces)
- Columns 42-43: State ID code (2-digit integer)
- Columns 44-47: Station ID (4-digit integer)
- Columns 48-49: IG code (2-digit integer, unused)

**Line 2** — Geographic location
Contains labeled fields: `LATT=`, `LONG=`, `YEARS=`, `TYPE=`
- LATT: latitude in decimal degrees (positive = north)
- LONG: longitude in decimal degrees (negative = west)
- YEARS: years of station record (may appear with trailing decimal point)
- TYPE: storm type code (integer 1-4)

**Line 3** — Elevation and reference precipitation
Contains labeled fields: `ELEVATION =` (feet above sea level), `TP5 =`, `TP6=`

## Precipitation Statistics (Lines 4-8)

All use Fortran format `FORMAT(8X,12F6.2)`:
skip the first 8 characters (label), then read 12 values each occupying
exactly 6 character positions.

| Line | Label    | Description                                     | Units  |
|------|----------|-------------------------------------------------|--------|
| 4    | MEAN P   | Mean daily precipitation on wet days            | inches |
| 5    | S DEV P  | Standard deviation of daily precipitation       | inches |
| 6    | SKEW  P  | Skew coefficient of daily precipitation         | —      |
| 7    | P(W/W)   | Probability of wet day following wet day         | 0–1    |
| 8    | P(W/D)   | Probability of wet day following dry day         | 0–1    |

## Temperature (Lines 9-12)

Format: `FORMAT(8X,12F6.2)`, all values in degrees Fahrenheit.

| Line | Label    | Description                        |
|------|----------|------------------------------------|
| 9    | TMAX AV  | Mean daily maximum temperature     |
| 10   | TMIN AV  | Mean daily minimum temperature     |
| 11   | SD TMAX  | Std dev of daily max temperature   |
| 12   | SD TMIN  | Std dev of daily min temperature   |

## Solar Radiation and Precipitation Intensity (Lines 13-15)

Format: `FORMAT(8X,12F6.2)`

| Line | Label    | Description                                          | Units    |
|------|----------|------------------------------------------------------|----------|
| 13   | SOL.RAD  | Mean daily solar radiation                           | Langleys |
| 14   | SD SOL   | Std dev of daily solar radiation                     | Langleys |
| 15   | MX .5 P  | Mean maximum 30-minute precipitation intensity       | in/hr    |

## Dew Point and Time to Peak (Lines 16-17)

| Line | Label    | Format               | Description                              | Units |
|------|----------|----------------------|------------------------------------------|-------|
| 16   | DEW PT   | `FORMAT(8X,12F6.2)` | Mean daily dew point temperature         | °F    |
| 17   | Time Pk  | `FORMAT(8X,12F6.3)` | Cumulative time-to-peak distribution     | —     |

Note: Line 17 uses `F6.3` (3 decimal places) rather than `F6.2`.

## Wind Data (Lines 18-81)

16 compass directions, 4 lines per direction (64 lines total).
Directions in order: N, NNE, NE, ENE, E, ESE, SE, SSE, S, SSW, SW, WSW,
W, WNW, NW, NNW.

For each direction, all lines use `FORMAT(8X,12F6.2)`:

| Sub-line | Label prefix | Description                              | Units |
|----------|-------------|------------------------------------------|-------|
| 1        | % DIR       | Percentage of time from this direction   | %     |
| 2        | MEAN        | Mean wind speed                          | m/s   |
| 3        | STD DEV     | Standard deviation of wind speed         | m/s   |
| 4        | SKEW        | Skew coefficient of wind speed           | —     |

## Calm and Metadata (Lines 82+)

**Line 82** — `CALM`: percentage of calm conditions by month.
Format: `FORMAT(8X,12F6.2)`

**Lines 83+** — Interpolation source station metadata. This section is
optional and its format is not standardized. It may be absent or contain
station names and weighting factors used during parameter interpolation.
