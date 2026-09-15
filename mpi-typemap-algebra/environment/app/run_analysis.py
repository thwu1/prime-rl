"""Run the MPI datatype layout analysis."""
from mpi_types import analyze

if __name__ == "__main__":
    results = analyze("/app/type_defs.json", "/app/results.json")
    for name, props in results.items():
        print(f"{name}: extent={props['extent']}, size={props['size']}")
