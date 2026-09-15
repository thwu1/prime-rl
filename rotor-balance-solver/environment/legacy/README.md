# Legacy Balance Analysis Tool

Command-line tool for rotating machinery balance analysis.

## Usage

    python3 balance_tool.py config.json

Reads a JSON configuration and prints results to stdout.

## Supported Modes

- `rotating`: Multi-plane rotating mass balance. Determines correction masses
  and angles for two correction planes to achieve static and dynamic balance.
- `reciprocating`: Inline reciprocating engine balance analysis. Evaluates
  primary force and moment balance.

## Known Issues

- Secondary force/moment analysis for reciprocating mode is not implemented
- Flywheel analysis mode is not available
- Only JSON input is supported
- Angle output may not be normalized
- Some calculation results have been reported as inaccurate
