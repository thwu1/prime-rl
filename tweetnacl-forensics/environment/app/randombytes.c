#include <fcntl.h>
#include <unistd.h>

void randombytes(unsigned char *x, unsigned long long xlen)
{
    int fd = open("/dev/urandom", O_RDONLY);
    if (fd < 0) return;
    while (xlen > 0) {
        ssize_t n = read(fd, x, xlen);
        if (n < 1) break;
        x += n;
        xlen -= (unsigned long long)n;
    }
    close(fd);
}
