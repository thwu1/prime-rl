# BIDS Physiological Recordings Format Reference

## File Format

Continuous physiological recordings use `_physio.<tsv.gz|json>` file pairs.
TSV.GZ files are gzip-compressed, tab-separated values WITHOUT headers.
Column definitions are provided in the accompanying JSON sidecar.

The `recording-<label>` entity MAY be used to distinguish between several
recording files. Recordings with different metadata such as sampling
frequencies or recording devices MUST be stored in separate files with
different `recording-<label>` entities.

## JSON Sidecar Metadata

Required fields for `_physio.json` sidecars:

- `Columns`: array of column names corresponding to TSV columns in order
- `SamplingFrequency`: sampling rate in Hz
- `StartTime`: recording start time relative to task onset

The field `PhysioType` indicates the type of recording. If absent, it
defaults to `"generic"`. Specific recording types have separate column
prescriptions (see Eye-Tracking section).

Each column named in `Columns` MAY have its own metadata entry describing
`Description`, `Units`, `LongName`, etc.

## BIDS Inheritance

Metadata sidecars follow the BIDS inheritance principle. A task-level
sidecar at the dataset root (e.g., `task-<label>_physio.json`) provides
default metadata for all matching recordings. A run-level sidecar in the
same directory as the data file (with the same entities) overrides
task-level values.

When resolving metadata, load the task-level sidecar first, then apply
run-level overrides. This inheritance applies equally to `_physio.json`
and `_events.json` sidecars.

## Physioevents Files

Physiology event files `_physioevents.tsv.gz` annotate continuous
recordings with classified discrete events. They follow the same
compressed, headerless TSV format.

A corresponding `_physioevents.json` sidecar defines columns and metadata,
including `OnsetSource` which specifies how onset values map to the
continuous recording's time base.

## Missing Data

The string `n/a` represents missing or not-applicable data in TSV files.
