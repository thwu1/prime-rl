#!/usr/bin/env python3
# -*- Mode: Python -*-
#------------------------------------------------------------------------------#
#  DFTB+: general package for performing fast atomistic simulations            #
#  Copyright (C) 2006 - 2025  DFTB+ developers group                           #
#                                                                              #
#  See the LICENSE file for terms of usage and distribution.                   #
#------------------------------------------------------------------------------#
#
# tagdiff -- utility to compare numerical results of calculations
# This is the REFERENCE IMPLEMENTATION for the tagdiff comparison tool.
# The task requires implementing equivalent functionality in shell.
#
from __future__ import print_function
import sys
import os.path
import re
import gzip
from argparse import ArgumentParser
from tagreader import InvalidEntry, ConversionError, IntConverter
from tagreader import TaggedCollection, ResultParser
from uncommlines import UncommLines

VERSION = 0.2
DESCRIPTION = """Compares two tagged output files according the tolerances
in config file(s).
"""

RES_OK = 0
RES_SKIPPED = 1
RES_FAILED = 2
RES_ERROR = 3
EXIT_OK = 0
EXIT_ERROR = 1
DEFAULT_CONFIG = "tagdiff.conf"

class DiffError(Exception):
    pass

class Diff(object):
    def __call__(self, orig, new):
        return None
    def __str__(self):
        return "general"

class DiffElement(Diff):
    def __call__(self, orig, new):
        try:
            diff = max(map(lambda x,y: abs(x-y), orig.value, new.value))
        except Exception as ee:
            raise DiffError("Exception (%s) while building difference" % str(ee))
        return diff
    def __str__(self):
        return "element"

class DiffVector(Diff):
    def __init__(self, nElement):
        self.__nElement = nElement

    def __call__(self, orig, new):
        if self.__nElement == -1:
            nElement = orig.shape[0]
        else:
            nElement = self.__nElement
        if (len(orig.value) != len(new.value) or len(orig.value) % nElement != 0):
            raise DiffError("Invalid nr. of elements")
        diff2 = []
        try:
            for ii in range(0, len(orig.value), nElement):
                origvals = orig.value[ii : ii + nElement]
                newvals = new.value[ii : ii + nElement]
                diffs = [abs(x - y)**2 for x, y in zip(origvals, newvals)]
                totaldiff = sum(diffs)
                diff2.append(totaldiff)
            maxdiff = max(diff2)**0.5
        except Exception as ee:
            raise DiffError("Exception (%s) while building difference" % str(ee))
        return maxdiff

    def __str__(self):
        return "vector:%d" % self.__nElement

class ToleranceEntry(object):
    __compFuncs = {
        "element": (DiffElement, ()),
        "vector": (DiffVector, (IntConverter(nolist=True),))
    }

    def __init__(self, pattern, value, compFuncName, compFuncArgs, keep):
        field = ":".join([compFuncName,] + list(compFuncArgs))
        self.__str = " @ ".join([pattern, value, field, keep])
        try:
            self.__pattern = re.compile(pattern)
        except re.error:
            raise InvalidEntry(msg="Invalid regular expression")
        self.__value = None
        try:
            self.__value = float(value)
            self.__value = int(value)
        except ValueError:
            if self.__value is None:
                raise InvalidEntry(msg="Invalid tolerance value")
        failed = True
        msg = ""
        if compFuncName in self.__compFuncs:
            (compFunc, argConverters) = self.__compFuncs[compFuncName]
            if len(argConverters) == len(compFuncArgs):
                try:
                    args = [argConverters[ii](compFuncArgs[ii]) for ii in range(len(compFuncArgs))]
                    self.__compFunc = compFunc(*args)
                    failed = False
                except ConversionError as msg:
                    pass
        else:
            msg = "Invalid function name"
        if failed:
            raise InvalidEntry(msg="Invalid comparison function '%s' (%s)" % (compFuncName, msg))
        self.__keep = (keep == "keep")

    @property
    def pattern(self):
        return self.__pattern
    @property
    def value(self):
        return self.__value
    @property
    def compFunc(self):
        return self.__compFunc
    @property
    def keep(self):
        return self.__keep
    def __str__(self):
        return self.__str

class ConfigParser(object):
    __defCompFunc = "element"
    __defCompFuncArgs = ()
    __defFlag = "nokeep"

    def __init__(self, file):
        self.__file = file

    def iterateEntries(self):
        for (line, iLine) in UncommLines(self.__file, returnLineNr=True):
            words = line.split("@")
            if len(words) < 2:
                raise InvalidEntry(iLine+1, iLine+2, "Not enough fields")
            pattern = words[0].strip()
            value = words[1].strip()
            if len(words) < 3 or words[2].strip() == "":
                compFunc = self.__defCompFunc
                compFuncArgs = self.__defCompFuncArgs
            else:
                tokens = [s.strip() for s in words[2].split(":")]
                compFunc = tokens[0]
                compFuncArgs = tuple(tokens[1:])
            if len(words) < 4 or words[3].strip() == "":
                flag = self.__defFlag
            else:
                flag = words[3].strip()
            try:
                te = ToleranceEntry(pattern, value, compFunc, compFuncArgs, flag)
            except InvalidEntry as ee:
                raise InvalidEntry(iLine+1, iLine+2, ee.msg)
            yield te

    entries = property(iterateEntries, None, None, "Sequence of extracted entries.")

resultStr = {RES_OK: "OK", RES_SKIPPED: "Skipped", RES_FAILED: "Failed", RES_ERROR: "Error"}

def printResult(name, method, msg, result):
    res = resultStr[result]
    tmp = ["%-20s %-20s %-27s" % (name, method, msg)]
    sys.stdout.write("%s %-10s\n" % ("\n".join(tmp), res))

def printError(message):
    sys.stderr.write("ERROR::%s\n" % message)

def zOpen(filename, mode):
    if len(filename) > 3 and filename[-3:] == ".gz":
        return gzip.open(filename, mode)
    else:
        return open(filename, mode)

def parseOptions():
    parser = ArgumentParser(usage="%(prog)s [options] orig new", description=DESCRIPTION)
    parser.add_argument('--version', action='version', version=("%%(prog)s %s" % VERSION))
    parser.add_argument("-c", "--config", dest="configfile", action="append",
                        help="config file to use (multiple allowed)")
    parser.add_argument("-v", "--verbose", dest="verbose", action="store_true",
                        default=False, help="verbose mode")
    options, args = parser.parse_known_args()
    if not args or len(args) < 2:
        parser.print_help()
        sys.exit(EXIT_ERROR)
    return (options, args)

def main():
    options, args = parseOptions()
    oldFile, newFile = args[:2]
    if options.configfile:
        confFiles = options.configfile[:]
    else:
        confFiles = [os.path.join(os.path.dirname(sys.argv[0]), DEFAULT_CONFIG)]

    configEntries = []
    for confFile in confFiles:
        if options.verbose:
            print("# Reading config file `%s'" % confFile)
        try:
            f = zOpen(confFile, "r")
            configEntries += [ce for ce in ConfigParser(f).entries]
        except InvalidEntry as ee:
            printError("Invalid entry (%s) in file '%s' between lines %d and %d"
                       % (ee.msg, confFile, ee.start, ee.end))
            f.close()
            return EXIT_ERROR
        except IOError:
            printError("Input/output error for file '%s'" % (confFile,))
            return EXIT_ERROR
        f.close()

    if options.verbose:
        print("# Reading old tagged file `%s'" % oldFile)
    try:
        f = zOpen(oldFile, "r")
        old = TaggedCollection(ResultParser(f).entries)
    except InvalidEntry as ee:
        printError("Invalid entry (%s) in file '%s' between lines %d and %d"
                   % (ee.msg, oldFile, ee.start, ee.end))
        f.close()
        return EXIT_ERROR
    except IOError:
        printError("Input/output error for file '%s'" % (oldFile,))
        return EXIT_ERROR
    f.close()

    if options.verbose:
        print("# Reading new tagged file `%s'" % newFile)
    try:
        f = zOpen(newFile, "r")
        new = TaggedCollection(ResultParser(f).entries)
    except InvalidEntry as ee:
        printError("Invalid entry (%s) in file '%s' between lines %d and %d"
                   % (ee.msg, newFile, ee.start, ee.end))
        f.close()
        return EXIT_ERROR
    except IOError:
        printError("Input/output error for file '%s'" % (newFile,))
        return EXIT_ERROR
    f.close()

    for configEntry in configEntries:
        if options.verbose:
            print(" # Processing rule:     `%s'" % configEntry)
        compFunc = configEntry.compFunc
        oldEntries = old.getMatchingEntries(configEntry.pattern)
        for oldEntry in oldEntries:
            name = oldEntry.name
            newEntry = new.getEntry(name)
            if not configEntry.keep:
                old.delEntry(name)
                new.delEntry(name)
            if not newEntry:
                printResult(name, compFunc, "Not found in new", RES_SKIPPED)
                continue
            if not oldEntry.isComparable(newEntry):
                printResult(name, compFunc, "Mismatching data", RES_ERROR)
                continue
            try:
                result = compFunc(oldEntry, newEntry)
            except DiffError as msg:
                printResult(name, compFunc, "Difference building error (%s)" % msg, RES_ERROR)
                continue
            passed = (result <= configEntry.value)
            if passed:
                msg = "%-20s" % (str(result))
                res = RES_OK
            else:
                msg = "%-20s" % (str(result))
                res = RES_FAILED
            printResult(name, compFunc, msg, res)

    return EXIT_OK

if __name__ == "__main__":
    status = main()
    sys.exit(status)
