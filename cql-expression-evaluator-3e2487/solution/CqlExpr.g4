grammar CqlExpr;


// Simplified CQL grammar for standalone expression parsing.
// Adapted from HL7 CQL v1.5 grammar — removed library/definition rules,
// multi-word implicit tokens, and import directives.

prog : expression EOF ;

expression
    : expressionTerm                                                        #termExpression
    | query                                                                 #queryExpression
    | expression 'is' 'not'? ('null' | 'true' | 'false')                   #booleanExpression
    | expression 'is' typeSpecifier                                         #isTypeExpression
    | expression 'as' typeSpecifier                                         #asTypeExpression
    | 'cast' expression 'as' typeSpecifier                                  #castExpression
    | 'not' expression                                                      #notExpression
    | 'exists' expression                                                   #existenceExpression
    | expression 'between' expressionTerm 'and' expressionTerm              #betweenExpression
    | expression ('union' | 'intersect' | 'except') expression              #setExpression
    | expression ('<=' | '<' | '>' | '>=') expression                       #inequalityExpression
    | expression ('=' | '!=' | '~' | '!~') expression                      #equalityExpression
    | expression ('in' | 'contains') expression                             #membershipExpression
    | expression ('includes' | 'included' 'in') expression                  #inclusionExpression
    | expression 'properly' ('includes' | 'included' 'in') expression       #properInclusionExpression
    | expression 'and' expression                                           #andExpression
    | expression ('or' | 'xor') expression                                  #orExpression
    | expression 'implies' expression                                       #impliesExpression
    ;

query
    : sourceClause whereClause? returnClause? sortClause?
    ;

sourceClause
    : 'from'? aliasedQuerySource (',' aliasedQuerySource)*
    ;

aliasedQuerySource
    : querySource alias
    ;

querySource
    : '(' expression ')'
    ;

alias
    : IDENTIFIER
    ;

whereClause
    : 'where' expression
    ;

returnClause
    : 'return' ('all' | 'distinct')? expression
    ;

sortClause
    : 'sort' sortDirection
    ;

sortDirection
    : 'asc' | 'ascending' | 'desc' | 'descending'
    ;

expressionTerm
    : term                                                                  #termExpressionTerm
    | expressionTerm '.' qualifiedInvocation                                #invocationExpressionTerm
    | expressionTerm '[' expression ']'                                     #indexedExpressionTerm
    | 'convert' expression 'to' typeSpecifier                              #conversionExpressionTerm
    | ('+' | '-') expressionTerm                                            #polarityExpressionTerm
    | 'successor' 'of' expressionTerm                                       #successorExpressionTerm
    | 'predecessor' 'of' expressionTerm                                     #predecessorExpressionTerm
    | 'singleton' 'from' expressionTerm                                     #singletonFromExpressionTerm
    | ('minimum' | 'maximum') namedTypeSpecifier                            #typeExtentExpressionTerm
    | dateTimeComponent 'from' expressionTerm                               #dateTimeComponentExpressionTerm
    | expressionTerm '^' expressionTerm                                     #powerExpressionTerm
    | expressionTerm ('*' | '/' | 'div' | 'mod') expressionTerm            #multiplicationExpressionTerm
    | expressionTerm ('+' | '-' | '&') expressionTerm                      #additionExpressionTerm
    | 'if' expression 'then' expression 'else' expression                  #ifThenElseExpressionTerm
    | 'case' expression? caseExpressionItem+ 'else' expression 'end'       #caseExpressionTerm
    | ('distinct' | 'flatten') expression                                   #aggregateExpressionTerm
    ;

caseExpressionItem
    : 'when' expression 'then' expression
    ;

dateTimeComponent
    : 'year' | 'month' | 'week' | 'day' | 'hour' | 'minute' | 'second' | 'millisecond'
    | 'date' | 'time' | 'timezoneoffset'
    ;

term
    : invocation                                                            #invocationTerm
    | literal                                                               #literalTerm
    | intervalSelector                                                      #intervalSelectorTerm
    | tupleSelector                                                         #tupleSelectorTerm
    | listSelector                                                          #listSelectorTerm
    | '(' expression ')'                                                    #parenthesizedTerm
    ;

qualifiedInvocation
    : referentialIdentifier                                                 #qualifiedMemberInvocation
    | qualifiedFunction                                                     #qualifiedFunctionInvocation
    ;

qualifiedFunction
    : identifierOrKeyword '(' paramList? ')'
    ;

invocation
    : referentialIdentifier                                                 #memberInvocation
    | fnCall                                                                #functionInvocation
    | '$this'                                                               #thisInvocation
    | '$index'                                                              #indexInvocation
    | '$total'                                                              #totalInvocation
    ;

fnCall
    : identifierOrKeyword '(' paramList? ')'
    ;

paramList
    : expression (',' expression)*
    ;

intervalSelector
    : 'Interval' ('['|'(') expression ',' expression (']'|')')
    ;

tupleSelector
    : 'Tuple'? '{' (':' | (tupleElementSelector (',' tupleElementSelector)*)) '}'
    ;

tupleElementSelector
    : referentialIdentifier ':' expression
    ;

listSelector
    : ('List' ('<' typeSpecifier '>')?)? '{' (expression (',' expression)*)? '}'
    ;

typeSpecifier
    : namedTypeSpecifier
    | listTypeSpecifier
    | intervalTypeSpecifier
    ;

namedTypeSpecifier
    : identifierOrKeyword ('.' identifierOrKeyword)*
    ;

listTypeSpecifier
    : 'List' '<' typeSpecifier '>'
    ;

intervalTypeSpecifier
    : 'Interval' '<' typeSpecifier '>'
    ;

literal
    : ('true' | 'false')                                                    #booleanLiteral
    | 'null'                                                                #nullLiteral
    | STRING                                                                #stringLiteral
    | NUMBER                                                                #numberLiteral
    | LONGNUMBER                                                            #longNumberLiteral
    | DATETIME                                                              #dateTimeLiteral
    | DATE                                                                  #dateLiteral
    | TIME                                                                  #timeLiteral
    | quantity                                                              #quantityLiteral
    ;

quantity
    : NUMBER unit
    ;

unit
    : dateTimePrecision
    | pluralDateTimePrecision
    | STRING
    ;

dateTimePrecision
    : 'year' | 'month' | 'week' | 'day' | 'hour' | 'minute' | 'second' | 'millisecond'
    ;

pluralDateTimePrecision
    : 'years' | 'months' | 'weeks' | 'days' | 'hours' | 'minutes' | 'seconds' | 'milliseconds'
    ;

referentialIdentifier
    : identifierOrKeyword
    ;

identifierOrKeyword
    : IDENTIFIER
    | DELIMITEDIDENTIFIER
    | QUOTEDIDENTIFIER
    | 'asc' | 'ascending' | 'by' | 'called' | 'code' | 'Code' | 'codesystem'
    | 'concept' | 'Concept' | 'context' | 'date' | 'default' | 'define'
    | 'desc' | 'descending' | 'display' | 'div' | 'end' | 'except'
    | 'fluent' | 'function' | 'implies' | 'include' | 'included' | 'includes'
    | 'intersect' | 'library' | 'meets' | 'mod' | 'overlaps' | 'parameter'
    | 'predecessor' | 'private' | 'properly' | 'public' | 'return' | 'start'
    | 'starting' | 'successor' | 'time' | 'timezoneoffset' | 'union' | 'using'
    | 'valueset' | 'version' | 'where' | 'width' | 'xor'
    ;

// Lexer rules

DATETIME
    : '@' DATEFORMAT 'T' TIMEFORMAT? TIMEZONEOFFSETFORMAT?
    ;

DATE
    : '@' DATEFORMAT
    ;

TIME
    : '@' 'T' TIMEFORMAT
    ;

fragment DATEFORMAT
    : [0-9][0-9][0-9][0-9] ('-'[0-9][0-9] ('-'[0-9][0-9])?)?
    ;

fragment TIMEFORMAT
    : [0-9][0-9] (':'[0-9][0-9] (':'[0-9][0-9] ('.'[0-9]+)?)?)?
    ;

fragment TIMEZONEOFFSETFORMAT
    : ('Z' | ('+' | '-') [0-9][0-9]':'[0-9][0-9])
    ;

LONGNUMBER
    : [0-9]+'L'
    ;

NUMBER
    : [0-9]+('.' [0-9]+)?
    ;

IDENTIFIER
    : ([A-Za-z] | '_')([A-Za-z0-9] | '_')*
    ;

DELIMITEDIDENTIFIER
    : '`' (ESC | .)*? '`'
    ;

QUOTEDIDENTIFIER
    : '"' (ESC | .)*? '"'
    ;

STRING
    : '\'' (ESC | .)*? '\''
    ;

WS
    : [ \r\n\t]+ -> channel(HIDDEN)
    ;

COMMENT
    : '/*' .*? '*/' -> channel(HIDDEN)
    ;

LINE_COMMENT
    : '//' ~[\r\n]* -> channel(HIDDEN)
    ;

fragment ESC
    : '\\' ([`'"\\/fnrt] | UNICODE)
    ;

fragment UNICODE
    : 'u' HEX HEX HEX HEX
    ;

fragment HEX
    : [0-9a-fA-F]
    ;
