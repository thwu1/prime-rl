ENTRY(reset_handler)

MEMORY
{
	FLASH (rx)  : ORIGIN = 0x00000000, LENGTH = 4M
	RAM   (rwx) : ORIGIN = 0x20000000, LENGTH = 4M
}

SECTIONS
{
	.text :
	{
		KEEP(*(.isr_vector))
		*(.text)
		*(.text.*)
		*(.rodata)
		*(.rodata.*)
		_sidata = .;
	} > FLASH

	.data : AT(_sidata)
	{
		_sdata = .;
		*(.data)
		*(.data.*)
		_edata = .;
	} > RAM

	.bss :
	{
		_sbss = .;
		*(.bss)
		*(.bss.*)
		*(COMMON)
		_ebss = .;
	} > RAM

	_estack = ORIGIN(RAM) + LENGTH(RAM);
	_heap_start = _ebss;
	_heap_end = _estack - 4096;
}
