/*
 * cobs_postcard.c - COBS + Postcard wire format decoder implementation
 *
 */
#include "cobs_postcard.h"

int cobs_decode(const uint8_t *input, size_t input_len,
                uint8_t *output, size_t output_max, size_t *output_len) {
    size_t idx = 0, out = 0;
    while (idx < input_len) {
        uint8_t code = input[idx++];
        if (code == 0) return -1;
        for (int i = 0; i < (int)(code - 1); i++) {
            if (idx >= input_len) return -1;
            if (out >= output_max) return -1;
            output[out++] = input[idx++];
        }
        if (code < 0xFF && idx < input_len) {
            if (out >= output_max) return -1;
            output[out++] = 0x00;
        }
    }
    *output_len = out;
    return 0;
}

int varint_decode(const uint8_t *data, size_t data_len, size_t *offset,
                  uint64_t *value, int max_bytes) {
    *value = 0;
    int shift = 0;
    for (int i = 0; i < max_bytes; i++) {
        if (*offset >= data_len) return -1;
        uint8_t byte = data[(*offset)++];
        *value |= (uint64_t)(byte & 0x7F) << shift;
        shift += 7;
        if ((byte & 0x80) == 0) return 0;
    }
    return -1;
}

int64_t zigzag_decode(uint64_t n) {
    return (int64_t)(n >> 1) ^ -(int64_t)(n & 1);
}

int decode_reading(const uint8_t *data, size_t data_len,
                   sensor_reading_t *reading) {
    size_t off = 0;
    uint64_t val;

    if (varint_decode(data, data_len, &off, &val, 3) != 0) return -1;
    if (val > 0xFFFF) return -1;
    reading->sensor_id = (uint16_t)val;

    if (varint_decode(data, data_len, &off, &val, 10) != 0) return -1;
    reading->timestamp_ms = val;

    if (varint_decode(data, data_len, &off, &val, 5) != 0) return -1;
    reading->temperature_cdeg = (int32_t)zigzag_decode(val);

    if (varint_decode(data, data_len, &off, &val, 3) != 0) return -1;
    if (val > 0xFFFF) return -1;
    reading->humidity_pct_x10 = (uint16_t)val;

    if (varint_decode(data, data_len, &off, &val, 5) != 0) return -1;
    if (val > 0xFFFFFFFF) return -1;
    reading->pressure_pa = (uint32_t)val;

    if (varint_decode(data, data_len, &off, &val, 3) != 0) return -1;
    if (val > 0xFFFF) return -1;
    reading->battery_mv = (uint16_t)val;

    if (varint_decode(data, data_len, &off, &val, 5) != 0) return -1;
    if (val > 3) return -1;
    reading->status = (uint8_t)val;

    if (varint_decode(data, data_len, &off, &val, 10) != 0) return -1;
    reading->num_sub_readings = (size_t)val;
    if (reading->num_sub_readings > MAX_SUB_READINGS) return -1;

    for (size_t i = 0; i < reading->num_sub_readings; i++) {
        if (varint_decode(data, data_len, &off, &val, 3) != 0) return -1;
        reading->sub_readings[i] = (int16_t)zigzag_decode(val);
    }

    return 0;
}

const char *status_name(uint8_t status) {
    static const char *names[] = {"Ok", "Warning", "Error", "Calibrating"};
    if (status > 3) return "Unknown";
    return names[status];
}
