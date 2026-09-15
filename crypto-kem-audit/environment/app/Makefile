CC      = gcc
CFLAGS  = -Wall -Wextra -std=c11 -I include -g -O1
AR      = ar

SRCDIR  = src
OBJDIR  = obj
LIB     = libsecops.a

SRCS    = $(wildcard $(SRCDIR)/*.c)
OBJS    = $(SRCS:$(SRCDIR)/%.c=$(OBJDIR)/%.o)

.PHONY: all clean test

all: $(LIB) test_basic

$(OBJDIR):
	mkdir -p $(OBJDIR)

$(OBJDIR)/%.o: $(SRCDIR)/%.c | $(OBJDIR)
	$(CC) $(CFLAGS) -c $< -o $@

$(LIB): $(OBJS)
	$(AR) rcs $@ $^

test_basic: tests/test_basic.c $(LIB)
	$(CC) $(CFLAGS) -o $@ $< $(LIB)

test: test_basic
	./test_basic

clean:
	rm -rf $(OBJDIR) $(LIB) test_basic
