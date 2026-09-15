CC      = gcc
CFLAGS  = -Wall -Wextra -O2
SRCDIR  = src
BINDIR  = bin

.PHONY: all clean

all: $(BINDIR)/supervisor

$(BINDIR)/supervisor: $(SRCDIR)/supervisor.c
	@mkdir -p $(BINDIR)
	$(CC) $(CFLAGS) -o $@ $<

clean:
	rm -f $(BINDIR)/supervisor
