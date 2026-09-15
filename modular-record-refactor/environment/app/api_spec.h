/*
 * api_spec.h — Target API contract for the record processing library.
 *
 * This file documents the public interface that all downstream daemon
 * code depends on.  The refactored record.h must provide these types
 * and function signatures exactly.  This file is a specification
 * document — do not #include it in the implementation.
 *
 * All functions listed here must be fully reentrant.
 */

/* ---- Error context type ---- */

/*
 * Per-call error context.  Callers allocate on the stack and pass a
 * pointer to API functions that can fail.  Replaces any global or
 * static error-reporting mechanism.
 */
typedef struct {
    int  code;          /* REC_ERR_* constant, or REC_OK (0) on success */
    char message[256];  /* Human-readable error description */
} rec_error_t;

/* ---- Function signatures ---- */

/*
 * Parse a binary record from wire format into *out.
 * Returns 0 (REC_OK) on success, negative REC_ERR_* code on failure.
 * On failure, *err is populated with error details.
 */
int rec_parse(const uint8_t *buf, size_t len, record_t *out, rec_error_t *err);

/*
 * Validate the fields of an already-parsed record.
 * Returns 0 on success, negative error code on failure.
 */
int rec_validate(const record_t *rec, rec_error_t *err);

/*
 * Format a record as a human-readable string into a caller-provided buffer.
 * Returns the number of characters written (excluding null terminator),
 * or a negative value on error.
 */
int rec_format(const record_t *rec, char *buf, size_t buf_len);

/*
 * Serialize a record to binary wire format.
 * Returns the number of bytes written, or 0 on failure.
 * On failure, *err is populated with error details.
 */
size_t rec_serialize(const record_t *rec, uint8_t *buf, size_t buf_len,
                     rec_error_t *err);

/*
 * Compute CRC32 (polynomial 0xEDB88320, reflected).
 * Standard test vector: rec_crc32("123456789", 9) == 0xCBF43926.
 */
uint32_t rec_crc32(const uint8_t *data, size_t len);
