// Verilator C++ testbench for hazard.sv
// Supports two modes: trace simulation and exhaustive enumeration
//

#include "Vhazard.h"
#include <verilated.h>
#include <cstdio>
#include <cstring>

int main(int argc, char** argv) {
    Verilated::commandArgs(argc, argv);
    Vhazard* top = new Vhazard;

    if (argc < 2) {
        fprintf(stderr, "Usage: %s <trace|enumerate>\n", argv[0]);
        delete top;
        return 1;
    }

    if (strcmp(argv[1], "trace") == 0) {
        // Process 200-cycle trace through actual RTL
        FILE* fin = fopen("/app/trace.csv", "r");
        if (!fin) { fprintf(stderr, "Cannot open trace.csv\n"); delete top; return 1; }

        FILE* fout = fopen("/app/trace_output.csv", "w");
        fprintf(fout, "cycle,StallF,StallD,StallE,StallM,StallW,FlushD,FlushE,FlushM,FlushW\n");

        char line[2048];
        fgets(line, sizeof(line), fin); // skip CSV header

        int cycle, v[13];
        while (fscanf(fin, "%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d",
                       &cycle, &v[0], &v[1], &v[2], &v[3], &v[4], &v[5],
                       &v[6], &v[7], &v[8], &v[9], &v[10], &v[11], &v[12]) == 14) {
            top->BPWrongE        = v[0];
            top->CSRWriteFenceM  = v[1];
            top->RetM            = v[2];
            top->TrapM           = v[3];
            top->StructuralStallD = v[4];
            top->LSUStallM       = v[5];
            top->IFUStallF       = v[6];
            top->FPUStallD       = v[7];
            top->ExternalStall   = v[8];
            top->DivBusyE        = v[9];
            top->FDivBusyE       = v[10];
            top->wfiM            = v[11];
            top->IntPendingM     = v[12];

            top->eval();

            fprintf(fout, "%d,%d,%d,%d,%d,%d,%d,%d,%d,%d\n",
                    cycle,
                    (int)top->StallF, (int)top->StallD, (int)top->StallE,
                    (int)top->StallM, (int)top->StallW,
                    (int)top->FlushD, (int)top->FlushE, (int)top->FlushM, (int)top->FlushW);
        }

        fclose(fin);
        fclose(fout);
        fprintf(stderr, "Trace simulation complete: 200 cycles\n");
    }
    else if (strcmp(argv[1], "enumerate") == 0) {
        // Exhaustively enumerate all 2^13 = 8192 input combinations
        FILE* fout = fopen("/app/enum_output.csv", "w");
        fprintf(fout, "bits,StallF,StallD,StallE,StallM,StallW,FlushD,FlushE,FlushM,FlushW\n");

        for (int bits = 0; bits < 8192; bits++) {
            top->BPWrongE         = (bits >> 0) & 1;
            top->CSRWriteFenceM   = (bits >> 1) & 1;
            top->RetM             = (bits >> 2) & 1;
            top->TrapM            = (bits >> 3) & 1;
            top->StructuralStallD = (bits >> 4) & 1;
            top->LSUStallM        = (bits >> 5) & 1;
            top->IFUStallF        = (bits >> 6) & 1;
            top->FPUStallD        = (bits >> 7) & 1;
            top->ExternalStall    = (bits >> 8) & 1;
            top->DivBusyE         = (bits >> 9) & 1;
            top->FDivBusyE        = (bits >> 10) & 1;
            top->wfiM             = (bits >> 11) & 1;
            top->IntPendingM      = (bits >> 12) & 1;

            top->eval();

            fprintf(fout, "%d,%d,%d,%d,%d,%d,%d,%d,%d,%d\n",
                    bits,
                    (int)top->StallF, (int)top->StallD, (int)top->StallE,
                    (int)top->StallM, (int)top->StallW,
                    (int)top->FlushD, (int)top->FlushE, (int)top->FlushM, (int)top->FlushW);
        }

        fclose(fout);
        fprintf(stderr, "Exhaustive enumeration complete: 8192 combinations\n");
    }
    else {
        fprintf(stderr, "Unknown mode: %s\n", argv[1]);
        delete top;
        return 1;
    }

    delete top;
    return 0;
}
