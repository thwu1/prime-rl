#include <stdint.h>

/* Linker script symbols */
extern uint32_t _sidata;
extern uint32_t _sdata;
extern uint32_t _edata;
extern uint32_t _sbss;
extern uint32_t _ebss;
extern uint32_t _estack;

extern void main(void);

void reset_handler(void);
void default_handler(void);

/* Weak aliases — override by defining these symbols in your code */
void nmi_handler(void)        __attribute__((weak, alias("default_handler")));
void hardfault_handler(void)  __attribute__((weak, alias("default_handler")));
void memmanage_handler(void)  __attribute__((weak, alias("default_handler")));
void busfault_handler(void)   __attribute__((weak, alias("default_handler")));
void usagefault_handler(void) __attribute__((weak, alias("default_handler")));
void svc_handler(void)        __attribute__((weak, alias("default_handler")));
void pendsv_handler(void)     __attribute__((weak, alias("default_handler")));
void systick_handler(void)    __attribute__((weak, alias("default_handler")));

__attribute__((section(".isr_vector")))
uint32_t *isr_vectors[] = {
	(uint32_t *) &_estack,            /* 0x00  Initial stack pointer */
	(uint32_t *) reset_handler,       /* 0x01  Reset */
	(uint32_t *) nmi_handler,         /* 0x02  NMI */
	(uint32_t *) hardfault_handler,   /* 0x03  Hard fault */
	(uint32_t *) memmanage_handler,   /* 0x04  Mem manage fault */
	(uint32_t *) busfault_handler,    /* 0x05  Bus fault */
	(uint32_t *) usagefault_handler,  /* 0x06  Usage fault */
	0, 0, 0, 0,                       /* 0x07-0x0A Reserved */
	(uint32_t *) svc_handler,         /* 0x0B  SVCall */
	0, 0,                             /* 0x0C-0x0D Reserved */
	(uint32_t *) pendsv_handler,      /* 0x0E  PendSV */
	(uint32_t *) systick_handler,     /* 0x0F  SysTick */
};

void reset_handler(void)
{
	uint32_t *src = &_sidata;
	uint32_t *dst = &_sdata;
	while (dst < &_edata)
		*dst++ = *src++;

	dst = &_sbss;
	while (dst < &_ebss)
		*dst++ = 0;

	main();
	while (1);
}

void default_handler(void)
{
	while (1);
}
