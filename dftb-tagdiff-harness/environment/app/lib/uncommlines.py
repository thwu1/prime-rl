#!/usr/bin/env python3
# -*- Mode: Python -*-
#------------------------------------------------------------------------------#
#  DFTB+: general package for performing fast atomistic simulations            #
#  Copyright (C) 2006 - 2025  DFTB+ developers group                           #
#                                                                              #
#  See the LICENSE file for terms of usage and distribution.                   #
#------------------------------------------------------------------------------#
#
# Simple iterator for reading non-empty and non-comment lines from a file

class FreeSepString(str):
    def strip(self, strSeparator=None):
        if strSeparator:
            if not (isinstance(strSeparator, str)):
                raise TypeError("expected a character buffer object")
            splitted = self.split(strSeparator)
            empties = [len(x) == 0 for x in splitted]
            try:
                i1 = empties.index(0)
            except ValueError:
                return ""
            rev = empties[:]
            rev.reverse()
            i2 = len(empties) - rev.index(0)
            return strSeparator.join(splitted[i1:i2])
        else:
            return str.strip(self)


class UncommLines(object):
    def __init__(self, file, iStartLine=0, iEndLine=0, strComment="#",
                 strSeparator=None, returnLineNr=None):
        if hasattr(file, 'readline'):
            self.__file = file
        else:
            raise AttributeError("Specified file has no readline() method")
        self.__iStartLine = iStartLine
        self.__iEndLine = iEndLine
        self.__strComment = strComment
        self.__strSeparator = strSeparator
        self.__iLine = 0
        self.__iReadLine = 0
        self.__returnLineNr = returnLineNr

    def __iter__(self):
        return self

    def next(self):
        while (not self.__iEndLine) or (self.__iLine < self.__iEndLine):
            try:
                line = self.__file.readline()
                self.__iReadLine += 1
            except IOError:
                pass
            else:
                if line:
                    tmp = (line.split(self.__strComment, 1)[0]).split("\n")[0]
                    tmp2 = FreeSepString(tmp).strip(self.__strSeparator)
                    if len(tmp2):
                        self.__iLine += 1
                        if self.__iLine > self.__iStartLine:
                            if self.__returnLineNr:
                                return (tmp2, self.__iReadLine - 1)
                            else:
                                return tmp2
                else:
                    break
        raise StopIteration

    def __next__(self):
        return self.next()
