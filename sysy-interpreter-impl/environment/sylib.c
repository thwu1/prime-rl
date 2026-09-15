#include <stdio.h>

int getint() {
    int n;
    scanf("%d", &n);
    return n;
}

int getch() {
    return getchar();
}

int getarray(int a[]) {
    int n;
    scanf("%d", &n);
    for (int i = 0; i < n; i++) {
        scanf("%d", &a[i]);
    }
    return n;
}

void putint(int a) {
    printf("%d", a);
}

void putch(int a) {
    printf("%c", a);
}

void putarray(int n, int a[]) {
    printf("%d:", n);
    for (int i = 0; i < n; i++) {
        printf(" %d", a[i]);
    }
    printf("\n");
}
