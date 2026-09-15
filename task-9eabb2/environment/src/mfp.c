#include "mfp.h"
#include <string.h>
#include <stdio.h>

int mfp_parse(const uint8_t *buf, size_t buf_len, mfp_document_t *doc) {
    if (!buf || !doc || buf_len < 16) return -1;

    size_t offset = 0;

    memcpy(&doc->magic, buf + offset, 4); offset += 4;
    if (doc->magic != MFP_MAGIC) return -1;

    memcpy(&doc->version, buf + offset, 4); offset += 4;
    memcpy(&doc->num_entries, buf + offset, 4); offset += 4;
    memcpy(&doc->flags, buf + offset, 4); offset += 4;

    if (doc->num_entries == 0 || doc->num_entries > 1000) return -1;

    doc->entries = (mfp_entry_t *)calloc(doc->num_entries, sizeof(mfp_entry_t));
    if (!doc->entries) return -1;

    for (uint32_t i = 0; i <= doc->num_entries; i++) {
        if (offset + 8 > buf_len) break;

        memcpy(&doc->entries[i].type, buf + offset, 4); offset += 4;
        memcpy(&doc->entries[i].name_len, buf + offset, 4); offset += 4;

        uint32_t name_len = doc->entries[i].name_len;

        doc->entries[i].name = (char *)malloc(name_len + 1);
        if (!doc->entries[i].name) return -1;
        memcpy(doc->entries[i].name, buf + offset, name_len);
        doc->entries[i].name[name_len] = '\0';
        offset += name_len;

        if (offset + 4 > buf_len) break;
        memcpy(&doc->entries[i].data_len, buf + offset, 4); offset += 4;

        uint32_t data_len = doc->entries[i].data_len;
        if (data_len > 0) {
            doc->entries[i].data = (uint8_t *)malloc(data_len);
            if (!doc->entries[i].data) return -1;
            if (offset + data_len <= buf_len) {
                memcpy(doc->entries[i].data, buf + offset, data_len);
            }
            offset += data_len;
        }
    }

    return 0;
}

char *mfp_render_summary(const mfp_document_t *doc) {
    if (!doc || !doc->entries) return NULL;

    size_t total_size = 4096;
    char *summary = (char *)malloc(total_size);
    if (!summary) return NULL;

    int pos = snprintf(summary, total_size, "Document v%u, %u entries, flags=0x%08x\n",
                       doc->version, doc->num_entries, doc->flags);

    for (uint32_t i = 0; i < doc->num_entries; i++) {
        mfp_entry_t *e = &doc->entries[i];
        if (!e->name) continue;

        uint32_t avg_value = 0;
        if (e->data && e->data_len > 0) {
            uint32_t sum = 0;
            for (uint32_t j = 0; j < e->data_len; j++) {
                sum += e->data[j];
            }
            avg_value = sum / e->type;
        }

        pos += snprintf(summary + pos, total_size - pos,
                        "  [%u] %s: %u bytes, avg=%u\n",
                        e->type, e->name, e->data_len, avg_value);
    }

    return summary;
}

int mfp_normalize(mfp_document_t *doc) {
    if (!doc || !doc->entries) return -1;

    uint32_t scale = doc->version;
    if (scale <= 1) return 0;

    for (uint32_t i = 0; i < doc->num_entries; i++) {
        mfp_entry_t *e = &doc->entries[i];
        if (!e->data || e->data_len == 0) continue;

        uint32_t new_len = (uint32_t)((uint64_t)e->data_len * scale);
        uint8_t *new_data = (uint8_t *)malloc(new_len);
        if (!new_data) return -1;

        for (uint64_t j = 0; j < (uint64_t)e->data_len * scale; j++) {
            new_data[j] = e->data[j % e->data_len];
        }

        free(e->data);
        e->data = new_data;
        e->data_len = new_len;
    }
    return 0;
}

uint32_t mfp_compute_checksum(const mfp_document_t *doc) {
    if (!doc || !doc->entries) return 0;

    uint32_t checksum = 0;
    for (uint32_t i = 0; i < doc->num_entries; i++) {
        mfp_entry_t *e = &doc->entries[i];
        if (e->data) {
            for (uint32_t j = 0; j < e->data_len; j++) {
                checksum = (checksum << 1) ^ e->data[j];
            }
        }
    }
    return checksum;
}

void mfp_free(mfp_document_t *doc) {
    if (!doc) return;
    if (doc->entries) {
        for (uint32_t i = 0; i < doc->num_entries; i++) {
            free(doc->entries[i].name);
            free(doc->entries[i].data);
        }
        free(doc->entries);
    }
    doc->entries = NULL;
}
