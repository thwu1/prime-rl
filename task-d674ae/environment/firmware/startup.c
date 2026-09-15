/*
 * startup.c — Minimal Cortex-M4 startup for TM4C123GXL
 */
#include <stdint.h>

extern uint32_t _stack_top;
extern uint32_t _data_start, _data_end, _data_load;
extern uint32_t _bss_start, _bss_end;
extern int main(void);

void Reset_Handler(void) {
    /* Copy .data from flash to SRAM */
    uint32_t *src = &_data_load;
    for (uint32_t *dst = &_data_start; dst < &_data_end; )
        *dst++ = *src++;

    /* Zero .bss */
    for (uint32_t *dst = &_bss_start; dst < &_bss_end; )
        *dst++ = 0;

    main();
    while (1)
        ;
}

void Default_Handler(void) {
    while (1)
        ;
}

__attribute__((section(".isr_vector"), used))
const uint32_t g_vectors[] = {
    (uint32_t)&_stack_top,
    (uint32_t)Reset_Handler,
    (uint32_t)Default_Handler,   /* NMI        */
    (uint32_t)Default_Handler,   /* HardFault  */
    (uint32_t)Default_Handler,   /* MemManage  */
    (uint32_t)Default_Handler,   /* BusFault   */
    (uint32_t)Default_Handler,   /* UsageFault */
};
