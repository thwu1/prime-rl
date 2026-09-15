Implement `/app/pi_extract.c` to extract individual hexadecimal digits of pi at arbitrary positions. The skeleton project at `/app/` provides `main.c`, `pi_extract.h`, and a `Makefile`. You must implement the `pi_hex_digit(long position)` function that returns the hex digit (0--15) at a given position.

Position 0 is the first hex digit after the decimal point in the hexadecimal expansion of pi. Pi in hex: `3.243F6A8885A308D31319...` -- position 0 returns 2, position 1 returns 4, position 3 returns 15 (F), etc.

Your implementation must use a digit-extraction algorithm (such as Bailey--Borwein--Plouffe) that computes digits at position d without computing all preceding digits. It must handle positions up to 10^6 and complete within 60 seconds per digit.

Build with `make` in `/app/`. The compiled binary `/app/pi_extract` accepts `<position> <count>` and prints the specified number of uppercase hex digits.