CREATE TABLE reference_metrics (
    kernel_name TEXT PRIMARY KEY,
    wavefronts INTEGER NOT NULL,
    total_conflicts INTEGER NOT NULL,
    conflict_free INTEGER NOT NULL
);

CREATE TABLE profiling_notes (
    kernel_name TEXT REFERENCES reference_metrics(kernel_name),
    note TEXT NOT NULL
);

INSERT INTO reference_metrics VALUES ('sequential', 1, 0, 1);
INSERT INTO reference_metrics VALUES ('column_major', 32, 31, 0);
INSERT INTO reference_metrics VALUES ('padded_column', 1, 0, 1);
INSERT INTO reference_metrics VALUES ('stride_7', 1, 0, 1);
INSERT INTO reference_metrics VALUES ('broadcast_groups', 2, 5, 0);
INSERT INTO reference_metrics VALUES ('quadratic_scatter', 2, 3, 0);

INSERT INTO profiling_notes VALUES ('sequential', 'Baseline: consecutive 4-byte element access, expect no bank conflicts');
INSERT INTO profiling_notes VALUES ('column_major', 'Known worst-case: column access of row-major tile, all threads hit same bank');
INSERT INTO profiling_notes VALUES ('padded_column', 'Padding strategy applied to column-major pattern');
INSERT INTO profiling_notes VALUES ('stride_7', 'Stride coprime to bank count should scatter across all banks');
INSERT INTO profiling_notes VALUES ('broadcast_groups', 'Mixed pattern: broadcasts within groups, conflicts between groups sharing banks');
INSERT INTO profiling_notes VALUES ('quadratic_scatter', 'Nonlinear scatter with modular arithmetic, partial conflicts expected');
