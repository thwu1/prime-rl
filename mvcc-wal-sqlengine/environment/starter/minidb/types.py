from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Any, List, Optional


class TokenType(Enum):
    CREATE = auto(); TABLE = auto(); INSERT = auto(); INTO = auto()
    VALUES = auto(); SELECT = auto(); FROM = auto(); WHERE = auto()
    UPDATE = auto(); SET = auto(); DELETE = auto()
    AND = auto(); OR = auto(); NOT = auto(); NULL = auto()
    TRUE = auto(); FALSE = auto()
    INT_TYPE = auto(); TEXT_TYPE = auto(); BOOLEAN_TYPE = auto()
    IDENT = auto(); INTEGER_LIT = auto(); STRING_LIT = auto()
    EQ = auto(); NEQ = auto(); LT = auto(); GT = auto()
    LTE = auto(); GTE = auto()
    LPAREN = auto(); RPAREN = auto(); COMMA = auto()
    SEMICOLON = auto(); STAR = auto()
    EOF = auto()


class ColumnType(Enum):
    INTEGER = "int"
    TEXT = "text"
    BOOLEAN = "boolean"


@dataclass
class Token:
    type: TokenType
    value: str


@dataclass
class ColumnDef:
    name: str
    col_type: ColumnType


@dataclass
class ResultSet:
    columns: List[str] = field(default_factory=list)
    rows: List[List[Any]] = field(default_factory=list)
    message: str = ""
