#ifndef EVREC_COMMON_H
#define EVREC_COMMON_H

/*
 */

#define EVREC_VERSION "1.0"
#define EVREC_BUF_SIZE 4096
#define EVREC_TIMING_FMT "%.6f %zd\n"

/*
 * Timing file format:
 * Each line: <delay_seconds> <byte_count>
 * delay_seconds: time elapsed since previous event (or session start)
 * byte_count: number of bytes in the corresponding data chunk
 *
 * Data file format:
 * Lines starting with '#' are metadata (header/footer).
 * All other content is raw captured output from the recorded command.
 */

#endif /* EVREC_COMMON_H */
