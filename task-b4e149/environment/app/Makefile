CC = gcc
CFLAGS = -Wall -Wextra -O2
BINDIR = bin
SRCDIR = src

PROGRAMS = $(BINDIR)/evrecord $(BINDIR)/evreplay $(BINDIR)/evanalyze

all: $(BINDIR) $(PROGRAMS)

$(BINDIR):
	mkdir -p $(BINDIR)

$(BINDIR)/evrecord: $(SRCDIR)/evrecord.c $(SRCDIR)/common.h
	$(CC) $(CFLAGS) -o $@ $<

$(BINDIR)/evreplay: $(SRCDIR)/evreplay.c $(SRCDIR)/common.h
	$(CC) $(CFLAGS) -o $@ $<

$(BINDIR)/evanalyze: $(SRCDIR)/evanalyze.c $(SRCDIR)/common.h
	$(CC) $(CFLAGS) -o $@ $<

clean:
	rm -rf $(BINDIR)

.PHONY: all clean
