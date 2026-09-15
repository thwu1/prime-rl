#ifndef MEMORY_CLASS_H
#define MEMORY_CLASS_H

#include "champsim.h"

#define NUM_TYPES 7
#define ROB_SIZE 352
#define LQ_SIZE 128
#define SQ_SIZE 72
#define NUM_INSTR_DESTINATIONS_SPARC 2

class MEMORY {};
struct BLOCK { uint32_t lru; };
struct PACKET {};
class PACKET_QUEUE {
public:
    std::string NAME;
    uint32_t SIZE;
    uint32_t occupancy;
    PACKET_QUEUE(std::string n, uint32_t s) : NAME(n), SIZE(s), occupancy(0) {}
};
class CORE_BUFFER {
public:
    CORE_BUFFER(std::string n, uint32_t s) {}
};
class LOAD_STORE_QUEUE {
public:
    LOAD_STORE_QUEUE(std::string n, uint32_t s) {}
};
struct input_instr {};
struct cloudsuite_instr {};
struct ooo_model_instr {};

#endif
