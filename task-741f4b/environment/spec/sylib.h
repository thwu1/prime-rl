/* SysY Runtime Library Header */

#ifndef __SYLIB_H_
#define __SYLIB_H_

/* Input functions */
int getint();              /* Read one integer from stdin */
int getch();               /* Read one character from stdin (returns ASCII value) */
int getarray(int a[]);     /* Read n, then n integers into a[]; return n */

/* Output functions */
void putint(int a);        /* Print integer a to stdout */
void putch(int a);         /* Print character with ASCII value a */
void putarray(int n, int a[]);  /* Print "n: a[0] a[1] ... a[n-1]\n" */

#endif
