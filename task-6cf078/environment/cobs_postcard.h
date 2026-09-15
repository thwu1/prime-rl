/*
 * cobs_postcard.h - COBS + Postcard wire format decoder library
 *
 */
#ifndef COBS_POSTCARD_H
#define COBS_POSTCARD_H

#include <stdint.h>
#include <stddef.h>

#define MAX_SUB_READINGS 64
#define STATUS_OK         0
#define STATUS_WARNING    1
#define STATUS_ERROR      2
#define STATUS_CALIBRATING 3

/* COBS decode: decode input[] (no sentinel) into output[].
 * Returns 0 on success, -1 on error. Sets *output_len. */
int cobs_decode(const uint8_t *input, size_t input_len,
                uint8_t *output, size_t output_max, size_t *output_len);

/* LEB128 varint decode. Reads from data[*offset], advances *offset.
 * Returns 0 on success, -1 on error. */
int varint_decode(const uint8_t *data, size_t data_len, size_t *offset,
                  uint64_t *value, int max_bytes);

/* Zigzag decode: unsigned → signed. */
int64_t zigzag_decode(uint64_t n);

/* Sensor reading struct (v1 schema). */
typedef struct {
    uint16_t sensor_id;
    uint64_t timestamp_ms;
    int32_t  temperature_cdeg;
    uint16_t humidity_pct_x10;
    uint32_t pressure_pa;
    uint16_t battery_mv;
    uint8_t  status;
    int16_t  sub_readings[MAX_SUB_READINGS];
    size_t   num_sub_readings;
} sensor_reading_t;

/* Decode a postcard-encoded SensorReading.
 * Returns 0 on success, -1 on error. */
int decode_reading(const uint8_t *data, size_t data_len,
                   sensor_reading_t *reading);

/* Status variant name lookup. */
const char *status_name(uint8_t status);

#endif /* COBS_POSTCARD_H */
