# BIDS Eye-Tracking Metadata Reference

## Identifying Eye-Tracking Recordings

Setting `PhysioType` to `"eyetrack"` in the physio JSON sidecar indicates
that the recording was acquired with an eye-tracker. Only recordings with
this value should be treated as eye-tracking data. Other values such as
`"cardiac"` or `"generic"` indicate different recording types.

## Column Requirements

Eye-tracking `_physio.tsv.gz` files MUST contain these columns:

- `timestamp`: sampling time registered by the device
- `x_coordinate`: horizontal gaze position on screen
- `y_coordinate`: vertical gaze position on screen
- `pupil_size`: pupil measurement (value of 0 indicates eye closure/blink)

**Important**: The column ORDER in the TSV file is defined by the `Columns`
array in the JSON sidecar. Different recordings may use different orderings
of the same column set.

## Recording Entity

The use of `recording-<label>` is REQUIRED for eye-tracking data.
Recommended labels are `"eye1"`, `"eye2"`, `"eye3"` for left, right,
and cyclopean recordings respectively. The actual eye is encoded by
the `RecordedEye` metadata field.

## Coordinate System

`SampleCoordinateSystem` set to `"gaze-on-screen"` indicates coordinates
are in screen-based pixel units. For this coordinate system, screen
geometry metadata becomes essential.

## Screen Geometry

Screen geometry is specified in `_events.json` sidecars (not physio
sidecars) under the `StimulusPresentation` object:

- `ScreenDistance`: viewing distance from participant to screen (meters)
- `ScreenSize`: physical screen dimensions [width, height] (meters)
- `ScreenResolution`: screen pixel dimensions [width, height] (pixels)
- `ScreenOrigin`: coordinate origin, e.g. ["top", "left"]

Screen geometry follows BIDS inheritance: a root-level `task-<label>_events.json`
provides defaults that may be overridden by a run-level `_events.json` in the
recording's directory.

## Oculomotor Events

Eye-tracking physioevents files classify continuous gaze data into discrete
oculomotor events. Common event types include fixations (stable gaze),
saccades (rapid eye movements), and blinks (eye closures). Saccade events
may carry amplitude measurements expressed in degrees of visual angle.

Example decompressed physioevents content from a real BIDS dataset:

```
7186806    72     fixation    0      n/a
7186879    231    saccade     1      n/a
7187111    6186   fixation    0      n/a
7193298    216    saccade     1      n/a
7193515    1286   fixation    0      n/a
```
