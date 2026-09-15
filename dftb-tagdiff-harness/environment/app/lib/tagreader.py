#!/usr/bin/env python3
# -*- Mode: Python -*-
#------------------------------------------------------------------------------#
#  DFTB+: general package for performing fast atomistic simulations            #
#  Copyright (C) 2006 - 2025  DFTB+ developers group                           #
#                                                                              #
#  See the LICENSE file for terms of usage and distribution.                   #
#------------------------------------------------------------------------------#
#
# tagreader -- parser for the tagged output of DFTB+
#

import re


class InvalidEntry(Exception):
    def __init__(self, start=0, end=0, msg=""):
        self.start = start
        self.end = end
        self.msg = msg

class ConversionError(Exception):
    pass


class Converter(object):
    def __init__(self, nolist=False):
        self.nolist = nolist

    def __call__(self, strValue):
        values = strValue.split()
        if self.nolist and len(values) > 1:
            raise ConversionError("Too many values")
        result = self.convert(values)
        if self.nolist:
            return result[0]
        else:
            return result

    def convert(self, values):
        return values


class FloatConverter(Converter):
    def convert(self, values):
        ll = []
        for val in values:
            try:
                ll.append(float(val))
            except Exception:
                raise ConversionError("Unable to convert float '%s'" % val)
        return ll


class IntConverter(Converter):
    def convert(self, values):
        ll = []
        for val in values:
            try:
                ll.append(int(val))
            except Exception:
                raise ConversionError("Unable to convert integer '%s'" % val)
        return ll


class ComplexConverter(Converter):
    def __call__(self, strValue):
        values = strValue.split()
        if len(values) % 2:
            raise ConversionError("Odd number of values")
        if self.nolist and len(values) != 2:
            raise ConversionError("Too many values")
        result = self.convert(values)
        if self.nolist:
            return result[0]
        else:
            return result

    def convert(self, values):
        ll = []
        for ii in range(0, len(values), 2):
            try:
                ll.append(complex(float(values[ii]), float(values[ii+1])))
            except Exception:
                raise ConversionError("Unable to convert complex '(%s,%s)'"
                                      % (values[ii], values[ii+1]))
        return ll


class LogicalConverter(Converter):
    def convert(self, values):
        ll = []
        for val in values:
            if val == 'T' or val == 't':
                ll.append(1)
            elif val == 'F' or val == 'f':
                ll.append(0)
            else:
                raise ConversionError("Unable to convert logical '%s'" % val)
        return ll


class TaggedEntry(object):
    __strToValue = {
        "integer": IntConverter(),
        "real": FloatConverter(),
        "complex": ComplexConverter(),
        "logical": LogicalConverter()
    }
    __validTypes = list(__strToValue.keys())

    def __init__(self, name, type, rank, shape, strValue):
        if type not in self.__validTypes:
            raise InvalidEntry(msg="Invalid data type '%s'" % type)
        self.__name = name
        self.__type = type
        self.__rank = rank
        self.__shape = shape
        try:
            self.__value = self.__strToValue[type](strValue)
        except ConversionError as msg:
            raise InvalidEntry(msg=msg)
        if (shape and len(shape) != rank) or (not shape and rank != 0):
            raise InvalidEntry(msg="Incompatible rank and shape")
        if shape and (len(self.__value) != product(shape)):
            raise InvalidEntry(msg="Invalid nr. of values")

    @property
    def name(self):
        return self.__name
    @property
    def type(self):
        return self.__type
    @property
    def rank(self):
        return self.__rank
    @property
    def shape(self):
        return self.__shape
    @property
    def value(self):
        return self.__value

    def isComparable(self, other):
        return (other.name == self.name and other.type == self.type
                and other.rank == self.rank and other.shape == self.shape)


class TaggedCollection(object):
    def __init__(self, entries):
        self.__entryNames = []
        self.__entryLines = []
        self.__entries = []
        self.addEntries(entries)

    def addEntries(self, entries):
        for entry in entries:
            taggedLine = ":".join((entry.name, entry.type, str(entry.rank),
                                   ",".join(map(str, entry.shape))))
            self.__entryNames.append(entry.name)
            self.__entryLines.append(taggedLine)
            self.__entries.append(entry)

    def getMatchingEntries(self, pattern):
        result = []
        for iEntry in range(len(self.__entries)):
            if pattern.match(self.__entryLines[iEntry]):
                result.append(self.__entries[iEntry])
        return result

    def getEntry(self, name):
        try:
            iEntry = self.__entryNames.index(name)
        except ValueError:
            result = None
        else:
            result = self.__entries[iEntry]
        return result

    def delEntry(self, name):
        try:
            iEntry = self.__entryNames.index(name)
        except ValueError:
            pass
        else:
            del self.__entries[iEntry]
            del self.__entryNames[iEntry]
            del self.__entryLines[iEntry]


class ResultParser(object):
    patTagLine = re.compile(r"""(?P<name>[^: ]+)\s*:
                                (?P<type>[^:]+):
                                (?P<rank>\d):
                                (?P<shape>(?:\d+(?:,\d+)*)*)
                            """, re.VERBOSE)

    def __init__(self, file):
        self.__file = file

    def iterateEntries(self):
        name = None
        type = None
        rank = None
        shape = None
        value = []
        iLine = 0
        for line in self.__file.readlines():
            iLine = iLine + 1
            match = self.patTagLine.match(line)
            if match:
                if name:
                    try:
                        yield TaggedEntry(name, type, rank, shape, " ".join(value))
                    except InvalidEntry as ee:
                        raise InvalidEntry(iTaggedLine + 1, iLine, msg=ee.msg)
                name = match.group("name")
                type = match.group("type")
                rank = int(match.group("rank"))
                if rank > 0:
                    shape = tuple([int(s) for s in match.group("shape").split(",")])
                else:
                    shape = ()
                value = []
                iTaggedLine = iLine
            else:
                value.append(line)
        if name:
            try:
                yield TaggedEntry(name, type, rank, shape, " ".join(value))
            except InvalidEntry as ee:
                raise InvalidEntry(iTaggedLine + 1, iLine, msg=ee.msg)

    entries = property(iterateEntries, None, None, "Iterator over parsed entries")


def product(elements):
    res = 1
    for elem in elements:
        res *= elem
    return res
