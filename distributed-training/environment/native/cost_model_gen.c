/*
 * Communication Cost Model Generator
 *
 * Reads a binary hardware specification file and computes communication
 * cost parameters for the distributed training simulation framework.
 * Outputs a Python module with the derived constants.
 *
 * Build:  make
 * Usage:  ./cost_model_gen hw_spec.bin /app/cost_model.py
 */
#include <stdio.h>
#include <stdlib.h>

int main(int argc, char *argv[]) {
    if (argc != 3) {
        fprintf(stderr, "Usage: %s <hw_spec.bin> <output.py>\n", argv[0]);
        return 1;
    }

    FILE *fin = fopen(argv[1], "rb");
    if (!fin) {
        perror("Cannot open hardware spec file");
        return 1;
    }

    int hidden, seq_length, checksum;
    double bandwidth, latency;

    if (fread(&hidden, sizeof(int), 1, fin) != 1 ||
        fread(&seq_length, sizeof(int), 1, fin) != 1 ||
        fread(&bandwidth, sizeof(double), 1, fin) != 1 ||
        fread(&latency, sizeof(double), 1, fin) != 1 ||
        fread(&checksum, sizeof(int), 1, fin) != 1) {
        fprintf(stderr, "Error: incomplete hardware spec file\n");
        fclose(fin);
        return 1;
    }
    fclose(fin);

    /* Validate checksum against hardware parameters */
    int expected = hidden ^ seq_length ^ (int)(bandwidth / 1000.0);
    if (checksum != expected) {
        fprintf(stderr, "Hardware spec checksum mismatch: got %d, expected %d\n",
                checksum, expected);
        fprintf(stderr, "The hw_spec.bin file may be corrupted.\n");
        return 1;
    }

    /* Derive cost model from hardware characteristics */
    double weight_msg_size = (double)hidden * hidden;
    double activation_msg_size = (double)hidden * seq_length;

    /* Collective ops transfer weight-sized messages */
    double collective_cost = weight_msg_size / bandwidth + latency;
    /* Point-to-point transfers activation-sized messages */
    double p2p_cost = activation_msg_size / bandwidth + latency;
    /* Weight update involves read + write of weight tensor */
    double update_cost = 2.0 * weight_msg_size / bandwidth + latency;

    /* Write Python cost model module */
    FILE *fout = fopen(argv[2], "w");
    if (!fout) {
        perror("Cannot create output file");
        return 1;
    }

    fprintf(fout, "# Communication cost model - generated from hardware spec\n");
    fprintf(fout, "# Regenerate: cd /app/native && make && "
                  "./cost_model_gen hw_spec.bin /app/cost_model.py\n\n");
    fprintf(fout, "HIDDEN = %d\n", hidden);
    fprintf(fout, "LENGTH = %d\n", seq_length);
    fprintf(fout, "COLLECTIVE_COST = %.6f\n", collective_cost);
    fprintf(fout, "P2P_COST = %.6f\n", p2p_cost);
    fprintf(fout, "UPDATE_COST = %.6f\n", update_cost);

    fclose(fout);

    printf("Generated %s (hidden=%d, length=%d, collective=%.4f, p2p=%.4f, update=%.4f)\n",
           argv[2], hidden, seq_length, collective_cost, p2p_cost, update_cost);
    return 0;
}
