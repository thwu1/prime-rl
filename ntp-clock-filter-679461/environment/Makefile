CC      = gcc
CFLAGS  = -Wall -Wextra -O2
LDFLAGS = -lm

OBJS    = ntp_ts.o ntp_filter.o ntp_select.o ntp_pipeline.o

ntp_pipeline: $(OBJS)
	$(CC) $(CFLAGS) -o $@ $^ $(LDFLAGS)

ntp_ts.o: ntp_ts.c ntp_ts.h ntp_types.h
ntp_filter.o: ntp_filter.c ntp_filter.h ntp_types.h
ntp_select.o: ntp_select.c ntp_select.h ntp_types.h
ntp_pipeline.o: ntp_pipeline.c ntp_types.h ntp_ts.h ntp_filter.h ntp_select.h

%.o: %.c
	$(CC) $(CFLAGS) -c -o $@ $<

.PHONY: clean
clean:
	rm -f $(OBJS) ntp_pipeline
