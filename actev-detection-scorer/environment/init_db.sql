CREATE TABLE videos (
    id INTEGER PRIMARY KEY,
    filename TEXT NOT NULL UNIQUE,
    num_frames INTEGER NOT NULL
);

CREATE TABLE activity_types (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE annotators (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE reference_annotations (
    id INTEGER PRIMARY KEY,
    activity_type_id INTEGER NOT NULL,
    video_id INTEGER NOT NULL,
    annotator_id INTEGER NOT NULL,
    start_frame INTEGER NOT NULL,
    end_frame INTEGER NOT NULL,
    FOREIGN KEY (activity_type_id) REFERENCES activity_types(id),
    FOREIGN KEY (video_id) REFERENCES videos(id),
    FOREIGN KEY (annotator_id) REFERENCES annotators(id)
);

INSERT INTO videos (id, filename, num_frames) VALUES
(1, 'video_001.mp4', 3000),
(2, 'video_002.mp4', 4500);

INSERT INTO activity_types (id, name) VALUES
(1, 'PersonRuns'),
(2, 'Closing'),
(3, 'Opening');

INSERT INTO annotators (id, name) VALUES
(1, 'annotator_1'),
(2, 'annotator_2');

-- PersonRuns: annotator_1
INSERT INTO reference_annotations (id, activity_type_id, video_id, annotator_id, start_frame, end_frame) VALUES
(1, 1, 1, 1, 100, 300),
(2, 1, 1, 1, 800, 1100),
(3, 1, 2, 1, 200, 600);
-- PersonRuns: annotator_2
INSERT INTO reference_annotations (id, activity_type_id, video_id, annotator_id, start_frame, end_frame) VALUES
(4, 1, 1, 2, 120, 280),
(5, 1, 1, 2, 810, 1090),
(6, 1, 2, 2, 250, 550);

-- Closing: annotator_1
INSERT INTO reference_annotations (id, activity_type_id, video_id, annotator_id, start_frame, end_frame) VALUES
(7, 2, 1, 1, 1500, 1800),
(8, 2, 2, 1, 1000, 1400),
(9, 2, 2, 1, 3000, 3500);
-- Closing: annotator_2
INSERT INTO reference_annotations (id, activity_type_id, video_id, annotator_id, start_frame, end_frame) VALUES
(10, 2, 1, 2, 1510, 1790),
(11, 2, 2, 2, 1050, 1350),
(12, 2, 2, 2, 3200, 3600);

-- Opening: annotator_1
INSERT INTO reference_annotations (id, activity_type_id, video_id, annotator_id, start_frame, end_frame) VALUES
(13, 3, 1, 1, 500, 700),
(14, 3, 2, 1, 2000, 2300);
-- Opening: annotator_2 (only video_001 — video_002 annotation is a singleton)
INSERT INTO reference_annotations (id, activity_type_id, video_id, annotator_id, start_frame, end_frame) VALUES
(15, 3, 1, 2, 520, 680);
