
grammar Lox;

program: declaration* EOF ;

declaration
    : classDecl
    | funDecl
    | varDecl
    | statement
    ;

classDecl: 'class' IDENTIFIER ('<' IDENTIFIER)? '{' function* '}' ;
funDecl: 'fun' function ;
function: IDENTIFIER '(' parameters? ')' block ;
parameters: IDENTIFIER (',' IDENTIFIER)* ;
varDecl: 'var' IDENTIFIER ('=' expression)? ';' ;

statement
    : exprStmt
    | forStmt
    | ifStmt
    | printStmt
    | returnStmt
    | whileStmt
    | block
    ;

exprStmt: expression ';' ;
forStmt: 'for' '(' forInit forCond forIncr ')' statement ;
forInit: varDecl | exprStmt | ';' ;
forCond: expression? ';' ;
forIncr: expression? ;
ifStmt: 'if' '(' expression ')' statement ('else' statement)? ;
printStmt: 'print' expression ';' ;
returnStmt: 'return' expression? ';' ;
whileStmt: 'while' '(' expression ')' statement ;
block: '{' declaration* '}' ;

expression: assignment ;
assignment: logic_or ('=' assignment)? ;
logic_or: logic_and ('or' logic_and)* ;
logic_and: equality ('and' equality)* ;
equality: comparison (('!=' | '==') comparison)* ;
comparison: term (('>' | '>=' | '<' | '<=') term)* ;
term: factor (('-' | '+') factor)* ;
factor: unary (('/' | '*') unary)* ;
unary: ('!' | '-') unary | call ;
call: primary (fnCall | propAccess)* ;
fnCall: '(' arguments? ')' ;
propAccess: '.' IDENTIFIER ;
arguments: expression (',' expression)* ;

primary
    : 'true'                        # trueExpr
    | 'false'                       # falseExpr
    | 'nil'                         # nilExpr
    | 'this'                        # thisExpr
    | NUMBER                        # numberExpr
    | STRING                        # stringExpr
    | IDENTIFIER                    # identifierExpr
    | '(' expression ')'            # groupExpr
    | 'super' '.' IDENTIFIER        # superExpr
    ;

// Lexer rules
NUMBER: DIGIT+ ('.' DIGIT+)? ;
STRING: '"' (~["])* '"' ;
IDENTIFIER: ALPHA (ALPHA | DIGIT)* ;

fragment ALPHA: [a-zA-Z_] ;
fragment DIGIT: [0-9] ;

LINE_COMMENT: '//' ~[\r\n]* -> skip ;
WS: [ \t\r\n]+ -> skip ;
