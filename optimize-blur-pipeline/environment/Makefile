CC = clang
CFLAGS = -O3 -Wall
LDLIBS = -lm

all: edge_detect edge_detect_ref

edge_detect: edge_detect.c
	$(CC) $(CFLAGS) -o $@ $< $(LDLIBS)

edge_detect_ref: edge_detect_ref.c
	$(CC) $(CFLAGS) -o $@ $< $(LDLIBS)

clean:
	rm -f edge_detect edge_detect_ref

.PHONY: all clean
