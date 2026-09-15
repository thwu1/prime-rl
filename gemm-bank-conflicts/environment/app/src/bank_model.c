/* bank_model.c - NVIDIA shared memory bank mapping model */

int compute_bank(int element_address, int element_bytes,
                 int bank_width_bytes, int num_banks) {
    return ((element_address * element_bytes) / bank_width_bytes) % num_banks;
}

int row_major_addr(int row, int col, int stride) {
    return row * stride + col;
}
