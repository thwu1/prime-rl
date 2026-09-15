CREATE TABLE packages (
    name TEXT PRIMARY KEY,
    version TEXT NOT NULL,
    description TEXT,
    provides TEXT DEFAULT '[]'
);

INSERT INTO packages VALUES ('glibc', '2.39-1', 'GNU C Library', '[]');
INSERT INTO packages VALUES ('zlib', '1.3.1-1', 'Compression library', '[]');
INSERT INTO packages VALUES ('openssl', '3.2.1-1', 'TLS/SSL and crypto library', '[]');
INSERT INTO packages VALUES ('pcre2', '10.42-1', 'Perl-Compatible Regular Expressions', '[]');
INSERT INTO packages VALUES ('nodejs', '21.6.1-1', 'Evented I/O for V8 JavaScript', '[]');
INSERT INTO packages VALUES ('cmake', '3.28.3-1', 'Cross-platform build system generator', '[]');
INSERT INTO packages VALUES ('unzip', '6.0-14', 'Extraction utility for zip archives', '[]');
INSERT INTO packages VALUES ('npm', '10.4.0-1', 'JavaScript package manager', '[]');
INSERT INTO packages VALUES ('git', '2.43.2-1', 'Distributed version control system', '[]');
