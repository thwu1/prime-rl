The directory `/app/circuits/` contains quantum programs written in Quil, Rigetti's quantum instruction language. The file `/app/spec.json` defines five analysis tasks to perform on these circuits, including a hardware topology compatibility analysis that uses the GraphViz DOT file at `/app/topology.dot`.

Parse all input files in their respective formats, perform the computations specified in each task, and write results to `/app/results.json` matching the output schema defined in each task's specification. One task additionally requires writing a GraphViz DOT file to a specified output path.

Quantum computing framework libraries (qiskit, cirq, pennylane, pyquil, strawberryfields, openfermion) are not permitted. Standard numerical and graph-processing libraries are permitted.