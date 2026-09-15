#ifndef PI_EXTRACT_H
#define PI_EXTRACT_H

/*
 * Return the hexadecimal digit (0-15) of pi at the given position.
 * Position 0 is the first hex digit after the decimal point.
 * Pi in hex: 3.243F6A8885A308D313198A2E...
 *   position 0 -> 2
 *   position 1 -> 4
 *   position 2 -> 3
 *   position 3 -> F (15)
 */
int pi_hex_digit(long position);

#endif /* PI_EXTRACT_H */
