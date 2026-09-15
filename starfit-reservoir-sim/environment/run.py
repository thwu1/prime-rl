#!/usr/bin/env python3
"""Run the reservoir simulation pipeline."""
from reservoir.io_utils import load_data
from reservoir.simulation import (
    run_simulation, write_results, write_nor_envelope, write_sensitivity,
)


def main():
    params, dates, inflows = load_data()

    # Main simulation
    results, balance = run_simulation(params, dates, inflows)
    write_results(results)
    print(
        f"Simulation complete. Mass balance relative error: "
        f"{balance['mass_balance_relative_error']:.2e}"
    )

    # NOR envelope
    write_nor_envelope(params)
    print("NOR envelope written.")

    # Sensitivity analysis
    write_sensitivity(params, dates, inflows)
    print("Sensitivity analysis written.")


if __name__ == "__main__":
    main()
