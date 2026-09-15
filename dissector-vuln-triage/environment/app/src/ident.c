#include <stdio.h>
#include <string.h>
#include <ctype.h>
#include "ndp.h"

/*
 * IDENT payload: sequence of extensions.
 * See ndp.h for the extension header format and known types.
 */

static int validate_printable(const uint8_t *data, size_t len) {
    for (size_t i = 0; i < len; i++) {
        if (!isprint((unsigned char)data[i])) {
            return 0;
        }
    }
    return 1;
}

static int dissect_iface_index(const uint8_t *data, size_t data_len) {
    if (data_len != 4) {
        fprintf(stderr, "IDENT: invalid interface index length %zu\n", data_len);
        return -1;
    }
    uint32_t index = read_u32_be(data);
    printf("IDENT: interface_index=%u\n", index);
    return 0;
}

static int dissect_iface_name(const uint8_t *data, size_t len) {
    /* Interface name must consist entirely of printable ASCII */
    if (!validate_printable(data, len)) {
        fprintf(stderr, "IDENT: interface name contains non-printable characters\n");
        return -1;
    }

    char ident_name[IDENT_NAME_BUF];

    /* Copy name, normalizing underscore separators to hyphens */
    size_t j = 0;
    for (size_t i = 0; i < len; i++) {
        ident_name[j++] = (data[i] == '_') ? '-' : data[i];
    }
    ident_name[j] = '\0';

    printf("IDENT: interface_name=\"%s\"\n", ident_name);
    return 0;
}

static int dissect_iface_addr4(const uint8_t *data, size_t data_len) {
    if (data_len != 4) {
        fprintf(stderr, "IDENT: invalid IPv4 address length %zu\n", data_len);
        return -1;
    }
    printf("IDENT: ipv4_address=%u.%u.%u.%u\n",
           data[0], data[1], data[2], data[3]);
    return 0;
}

int handle_ident(const uint8_t *payload, size_t len, uint8_t flags) {
    size_t offset = 0;
    int ext_count = 0;

    while (offset + IDENT_EXT_HEADER_SIZE <= len) {
        uint16_t class_num = read_u16_be(payload + offset);
        uint8_t c_type = payload[offset + 2];
        /* reserved byte at offset + 3 */
        uint16_t ext_length = read_u16_be(payload + offset + 4);

        if (ext_length < IDENT_EXT_HEADER_SIZE) {
            fprintf(stderr, "IDENT: extension length %u is too small\n", ext_length);
            return -1;
        }

        if (offset + ext_length > len) {
            fprintf(stderr, "IDENT: extension at offset %zu extends past payload\n", offset);
            return -1;
        }

        size_t data_len = ext_length - IDENT_EXT_HEADER_SIZE;
        const uint8_t *ext_data = payload + offset + IDENT_EXT_HEADER_SIZE;

        if (class_num == IDENT_CLASS_IFACE) {
            int ret = 0;
            switch (c_type) {
                case IDENT_CTYPE_INDEX:
                    ret = dissect_iface_index(ext_data, data_len);
                    break;
                case IDENT_CTYPE_NAME:
                    ret = dissect_iface_name(ext_data, data_len);
                    break;
                case IDENT_CTYPE_ADDR4:
                    ret = dissect_iface_addr4(ext_data, data_len);
                    break;
                default:
                    if (flags & NDP_FLAG_VERBOSE) {
                        fprintf(stderr, "IDENT: unknown c_type 0x%02X for class 0x%04X\n",
                                c_type, class_num);
                    }
                    break;
            }
            if (ret < 0)
                return ret;
        }

        offset += ext_length;
        ext_count++;
    }

    if (ext_count == 0) {
        fprintf(stderr, "IDENT: no extensions found\n");
        return -1;
    }

    return 0;
}
