/* gb_flip.h - minimal stub replacing Stanford GraphBase random number functions */
/* Provides the random number interface expected by Knuth's DLX programs */
#ifndef GB_FLIP_H
#define GB_FLIP_H
#include <stdlib.h>
static void gb_init_rand(long seed) { srand48(seed); }
static long gb_unif_rand(long m) { return m > 0 ? lrand48() % m : 0; }
#endif
