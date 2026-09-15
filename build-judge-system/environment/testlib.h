/*
 * Minimal testlib.h — supports registerTestlibCmd checkers.
 * Provides InStream for reading input/output/answer files
 * and quitf() for reporting verdicts.
 */
#ifndef _TESTLIB_H_
#define _TESTLIB_H_

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cstdarg>
#include <string>
#include <fstream>
#include <sstream>
#include <iostream>
#include <climits>
#include <cerrno>

const int _ok = 0;
const int _wa = 1;
const int _pe = 2;
const int _fail = 3;
const int _partially = 7;

static void quitf(int result, const char* fmt, ...) __attribute__((noreturn));

static void quitf(int result, const char* fmt, ...) {
    va_list args;
    va_start(args, fmt);
    const char* label;
    switch (result) {
        case _ok:        label = "ok "; break;
        case _wa:        label = "wrong answer "; break;
        case _pe:        label = "presentation error "; break;
        case _fail:      label = "FAIL "; break;
        case _partially: label = "partially correct "; break;
        default:         label = "unknown "; break;
    }
    fprintf(stderr, "%s", label);
    vfprintf(stderr, fmt, args);
    fprintf(stderr, "\n");
    va_end(args);
    exit(result);
}

class InStream {
private:
    std::ifstream _stream;
    std::string _name;
    bool _opened;

public:
    InStream() : _opened(false) {}

    void open(const char* filename) {
        _name = filename;
        _stream.open(filename);
        _opened = true;
        if (_stream.fail()) {
            fprintf(stderr, "Cannot open file '%s'\n", filename);
        }
    }

    void open(const std::string& filename) {
        open(filename.c_str());
    }

    int readInt() {
        int v;
        _stream >> v;
        return v;
    }

    int readInt(int lo, int hi, const std::string& name = "") {
        int v = readInt();
        if (v < lo || v > hi) {
            quitf(_fail, "Integer %d for '%s' out of range [%d, %d]",
                  v, name.c_str(), lo, hi);
        }
        return v;
    }

    long long readLong() {
        long long v;
        _stream >> v;
        return v;
    }

    double readDouble() {
        double v;
        _stream >> v;
        return v;
    }

    std::string readWord() {
        std::string s;
        _stream >> s;
        return s;
    }

    std::string readToken() {
        return readWord();
    }

    std::string readLine() {
        std::string s;
        std::getline(_stream, s);
        return s;
    }

    char readChar() {
        return (char)_stream.get();
    }

    void readEoln() {
        char c = readChar();
        if (c == '\r') {
            c = readChar();
        }
        if (c != '\n' && !_stream.eof()) {
            // skip
        }
    }

    void readEof() {
        // skip whitespace and check
        std::string s;
        _stream >> s;
        // nothing to enforce in minimal version
    }

    bool eof() {
        return _stream.eof();
    }

    bool seekEof() {
        char c;
        while (_stream.get(c)) {
            if (c != ' ' && c != '\t' && c != '\r' && c != '\n') {
                _stream.putback(c);
                return false;
            }
        }
        return true;
    }
};

InStream inf, ouf, ans;

static void registerTestlibCmd(int argc, char* argv[]) {
    if (argc < 4) {
        fprintf(stderr, "Usage: <checker> <input-file> <output-file> <answer-file>\n");
        exit(_fail);
    }
    inf.open(argv[1]);
    ouf.open(argv[2]);
    ans.open(argv[3]);
}

#endif /* _TESTLIB_H_ */
