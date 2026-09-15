/*
 * NEC2 Antenna Characterization Tool
 * Parses NEC2 deck and output files, cross-validates geometry,
 * and computes antenna performance metrics.
 *
 * Usage: nec2_char <deck.nec> <output.txt> [run_number]
 */


#include "nec2_types.h"
#include "nec2_parser.h"
#include "deck_parser.h"
#include "antenna_metrics.h"

static void print_json(const DeckData *deck, const SimRun *run,
                       double vswr, double max_cur,
                       double max_gain, double max_theta,
                       double avg_gain, double hpbw,
                       const ValidationResult *vr) {
    printf("{\n");

    printf("  \"deck\": {\n");
    printf("    \"num_wires\": %d,\n", deck->n_wires);
    printf("    \"total_segments\": %d,\n", deck->total_segments);
    if (deck->has_frequency)
        printf("    \"frequency_mhz\": %.4f,\n", deck->frequency_mhz);
    else
        printf("    \"frequency_mhz\": null,\n");
    if (deck->has_excitation) {
        printf("    \"excitation_tag\": %d,\n", deck->ex_tag);
        printf("    \"excitation_seg\": %d\n", deck->ex_seg);
    } else {
        printf("    \"excitation_tag\": null,\n");
        printf("    \"excitation_seg\": null\n");
    }
    printf("  },\n");

    printf("  \"output\": {\n");
    printf("    \"frequency_mhz\": %.4f,\n", run->frequency_mhz);
    printf("    \"impedance_real\": %.6e,\n", run->input.z_real);
    printf("    \"impedance_imag\": %.6e,\n", run->input.z_imag);
    printf("    \"vswr\": %.6f,\n", vswr);
    printf("    \"input_power\": %.6e,\n", run->power.input_power);
    printf("    \"radiated_power\": %.6e,\n", run->power.radiated_power);
    printf("    \"efficiency\": %.4f,\n", run->power.efficiency);
    printf("    \"max_current_mag\": %.6e,\n", max_cur);
    if (run->has_pattern) {
        printf("    \"max_gain_db\": %.4f,\n", max_gain);
        printf("    \"max_gain_theta\": %.2f,\n", max_theta);
    } else {
        printf("    \"max_gain_db\": null,\n");
        printf("    \"max_gain_theta\": null,\n");
    }
    if (avg_gain > -900.0)
        printf("    \"avg_power_gain\": %.6e,\n", avg_gain);
    else
        printf("    \"avg_power_gain\": null,\n");
    if (hpbw > 0.0)
        printf("    \"hpbw_deg\": %.4f\n", hpbw);
    else
        printf("    \"hpbw_deg\": null\n");
    printf("  },\n");

    printf("  \"validation\": {\n");
    printf("    \"segments_match\": %s,\n", vr->segments_match ? "true" : "false");
    printf("    \"excitation_match\": %s\n", vr->excitation_match ? "true" : "false");
    printf("  }\n");

    printf("}\n");
}

int main(int argc, char *argv[]) {
    if (argc < 3) {
        fprintf(stderr, "Usage: %s <deck.nec> <output.txt> [run_number]\n", argv[0]);
        return 1;
    }

    const char *deck_file = argv[1];
    const char *output_file = argv[2];
    int run_number = (argc >= 4) ? atoi(argv[3]) : 1;
    if (run_number < 1) run_number = 1;

    DeckData deck;
    SimRun run;

    if (parse_deck(deck_file, &deck) != 0) {
        fprintf(stderr, "Error parsing deck: %s\n", deck_file);
        return 1;
    }

    if (parse_nec2_output(output_file, run_number, &run) != 0) {
        fprintf(stderr, "Error parsing output: %s\n", output_file);
        return 1;
    }

    if (!run.has_input) {
        fprintf(stderr, "No input parameters for run %d\n", run_number);
        return 1;
    }

    double vswr = compute_vswr(run.input.z_real, run.input.z_imag);

    double max_cur = 0.0;
    for (int i = 0; i < run.n_currents; i++) {
        if (run.currents[i].i_mag > max_cur)
            max_cur = run.currents[i].i_mag;
    }

    double max_gain = -9999.0, max_theta = 0.0;
    double hpbw = -1.0;
    double avg_gain = -1.0;

    if (run.has_pattern) {
        find_max_gain(run.pattern, run.n_pattern, &max_gain, &max_theta);
        hpbw = compute_hpbw(run.pattern, run.n_pattern);
    }
    if (run.has_avg_gain) {
        avg_gain = run.avg_power_gain;
    }

    ValidationResult vr = validate_deck_vs_output(&deck, &run);

    print_json(&deck, &run, vswr, max_cur, max_gain, max_theta, avg_gain, hpbw, &vr);

    return 0;
}
