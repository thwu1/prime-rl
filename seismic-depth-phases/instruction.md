The file `/app/observations.json` contains seismic arrival-time picks from an earthquake recorded at 8 global seismic network stations. Examine the data to understand what event parameters are provided, what is missing, and what must be determined from the observations.

Produce a complete seismological characterization and write it to `/app/results.json` with the following exact structure:

```json
{
  "depth_km": <float>,
  "velocity_model": "iasp91",
  "stations": {
    "<STATION_CODE>": {
      "distance_deg": <float>,
      "arrivals": [
        {"time": "<UTC arrival time string>", "phase": "<phase name>", "residual_sec": <float>}
      ]
    }
  },
  "total_rms_residual_sec": <float>
}
```

Acceptance criteria:

- `velocity_model` must be `"iasp91"`.
- `depth_km` must be accurate to within ±3 km of the true focal depth.
- All 8 stations from the observations must appear in the output.
- Every observed arrival at each station must be assigned a phase label; the number of arrivals per station must match the input data, and each phase assignment must be correct.
- Arrivals within each station must be sorted by time.
- `distance_deg` is the epicentral distance in degrees and must be accurate to within 0.05°.
- `residual_sec` for each arrival equals the observed travel time minus the theoretical travel time for the assigned phase.
- `total_rms_residual_sec` is the root-mean-square of all individual residuals across all stations; it must be below 0.5 seconds.
- No individual |`residual_sec`| may exceed 1.0 second.