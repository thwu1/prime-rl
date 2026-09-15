CC      = gcc
CFLAGS  = -Wall -O0

PIPELINE_OBJS = basicop.o oper_32b.o levinson.o pipeline.o
SELFTEST_OBJS = basicop.o oper_32b.o selftest.o

all: pipeline selftest

pipeline: $(PIPELINE_OBJS)
	$(CC) $(CFLAGS) -o $@ $(PIPELINE_OBJS)

selftest: $(SELFTEST_OBJS)
	$(CC) $(CFLAGS) -o $@ $(SELFTEST_OBJS)

debug: CFLAGS += -g
debug: clean all

%.o: %.c
	$(CC) $(CFLAGS) -c $<

clean:
	rm -f *.o pipeline selftest

.PHONY: all clean debug
