// SQL PEG Grammar — corrected and extended
//

{
  function createList(head, tail, idx) {
    idx = idx || 3;
    const result = [head];
    for (let i = 0; i < tail.length; i++) {
      result.push(tail[i][idx]);
    }
    return result;
  }

  function buildBinaryExpr(op, left, right) {
    return { type: 'binary_expr', operator: op, left: left, right: right };
  }
}

start
  = __ stmt:union_stmt __ { return stmt; }

// ─── SET OPERATIONS ───

union_stmt
  = head:select_stmt tail:(__ set_op __ select_stmt)* __ ob:order_by_clause? __ lim:limit_clause? {
      let cur = head;
      for (let i = 0; i < tail.length; i++) {
        cur._next = tail[i][3];
        cur.set_op = tail[i][1];
        cur = cur._next;
      }
      if (ob) head._orderby = ob;
      if (lim) head._limit = lim;
      return head;
    }

set_op
  = "UNION"i __ "ALL"i { return 'UNION ALL'; }
  / "UNION"i { return 'UNION'; }
  / "INTERSECT"i { return 'INTERSECT'; }
  / "EXCEPT"i { return 'EXCEPT'; }

// ─── SELECT STATEMENT ───

select_stmt
  = select_stmt_nake
  / "(" __ s:select_stmt __ ")" {
      s._parentheses = true;
      return s;
    }

select_stmt_nake
  = __ cte:with_clause? __
    "SELECT"i ___
    dist:distinct_clause? __
    cols:column_clause __
    from:from_clause? __
    where:where_clause? __
    groupby:group_by_clause? __
    having:having_clause? __
    orderby:order_by_clause? __
    lim:limit_clause? __ {
      return {
        type: 'select',
        with: cte ? cte.items : null,
        recursive: cte ? cte.recursive : false,
        options: null,
        distinct: dist,
        columns: cols,
        from: from,
        where: where,
        groupby: groupby,
        having: having,
        orderby: orderby,
        limit: lim,
      };
    }

// ─── WITH / CTE ───

with_clause
  = "WITH"i ___ "RECURSIVE"i ___ head:cte_definition tail:(__ "," __ cte_definition)* {
      return { recursive: true, items: createList(head, tail) };
    }
  / "WITH"i ___ head:cte_definition tail:(__ "," __ cte_definition)* {
      return { recursive: false, items: createList(head, tail) };
    }

cte_definition
  = name:ident_name __ cols:cte_columns? __ "AS"i __ "(" __ stmt:union_stmt __ ")" {
      return { name: { value: name }, stmt: { ast: stmt }, columns: cols };
    }

cte_columns
  = "(" __ head:ident_name tail:(__ "," __ ident_name)* __ ")" {
      return createList(head, tail);
    }

// ─── DISTINCT ───

distinct_clause
  = "DISTINCT"i { return 'DISTINCT'; }

// ─── COLUMNS ───

column_clause
  = head:column_item tail:(__ "," __ column_item)* {
      return createList(head, tail);
    }

column_item
  = e:expr __ alias:alias_clause? {
      return { expr: e, as: alias };
    }

alias_clause
  = "AS"i ___ n:ident_name { return n; }
  / "AS"i ___ "\"" chars:[^"]+ "\"" { return chars.join(''); }
  / "AS"i ___ "`" chars:[^`]+ "`" { return chars.join(''); }

// ─── FROM CLAUSE ───

from_clause
  = "FROM"i ___ head:table_ref joins:(__ join_clause)+ {
      const result = [head];
      for (const j of joins) {
        result.push(j[1]);
      }
      return result;
    }
  / "FROM"i ___ head:table_ref tail:(__ "," __ table_ref)* {
      return createList(head, tail);
    }

table_ref
  = "(" __ s:union_stmt __ ")" __ alias:alias_clause? {
      return { expr: { ast: s }, as: alias, db: null, table: null };
    }
  / db:ident_name "." tbl:ident_name __ alias:alias_clause? {
      return { db: db, table: tbl, as: alias };
    }
  / tbl:ident_name __ alias:alias_clause? {
      return { db: null, table: tbl, as: alias };
    }

join_clause
  = jt:join_type ___ tr:table_ref __ "ON"i ___ cond:expr {
      return { ...tr, join: jt, on: cond };
    }
  / jt:join_type ___ tr:table_ref __ "USING"i __ "(" __ head:ident_name tail:(__ "," __ ident_name)* __ ")" {
      return { ...tr, join: jt, using: createList(head, tail) };
    }

join_type
  = "INNER"i ___ "JOIN"i { return 'INNER JOIN'; }
  / "LEFT"i ___ "OUTER"i ___ "JOIN"i { return 'LEFT OUTER JOIN'; }
  / "LEFT"i ___ "JOIN"i { return 'LEFT JOIN'; }
  / "RIGHT"i ___ "OUTER"i ___ "JOIN"i { return 'RIGHT OUTER JOIN'; }
  / "RIGHT"i ___ "JOIN"i { return 'RIGHT JOIN'; }
  / "FULL"i ___ "OUTER"i ___ "JOIN"i { return 'FULL OUTER JOIN'; }
  / "FULL"i ___ "JOIN"i { return 'FULL JOIN'; }
  / "CROSS"i ___ "JOIN"i { return 'CROSS JOIN'; }
  / "JOIN"i { return 'JOIN'; }

// ─── WHERE ───

where_clause
  = "WHERE"i ___ e:expr { return e; }

// ─── GROUP BY ───

group_by_clause
  = "GROUP"i ___ "BY"i ___ head:expr tail:(__ "," __ expr)* {
      return { columns: createList(head, tail) };
    }

// ─── HAVING ───

having_clause
  = "HAVING"i ___ e:expr { return e; }

// ─── ORDER BY ───

order_by_clause
  = "ORDER"i ___ "BY"i ___ head:order_item tail:(__ "," __ order_item)* {
      return createList(head, tail);
    }

order_item
  = e:expr ___ dir:("ASC"i / "DESC"i) ___ nl:nulls_spec {
      return { expr: e, type: dir.toUpperCase(), nulls: nl };
    }
  / e:expr ___ dir:("ASC"i / "DESC"i) {
      return { expr: e, type: dir.toUpperCase() };
    }
  / e:expr ___ nl:nulls_spec {
      return { expr: e, type: 'ASC', nulls: nl };
    }
  / e:expr {
      return { expr: e, type: 'ASC' };
    }

nulls_spec
  = "NULLS"i ___ "FIRST"i { return 'NULLS FIRST'; }
  / "NULLS"i ___ "LAST"i { return 'NULLS LAST'; }

// ─── LIMIT / OFFSET ───

limit_clause
  = "LIMIT"i ___ n:literal_number __ "OFFSET"i ___ o:literal_number {
      return { separator: 'offset', value: [n, o] };
    }
  / "LIMIT"i ___ n:literal_number __ "," __ o:literal_number {
      return { separator: ',', value: [n, o] };
    }
  / "LIMIT"i ___ n:literal_number {
      return { separator: '', value: [n] };
    }

// ─── EXPRESSIONS ───
// Proper operator precedence via layered rules

expr
  = or_expr

or_expr
  = left:and_expr __ "OR"i __ right:or_expr {
      return buildBinaryExpr('OR', left, right);
    }
  / and_expr

and_expr
  = left:comparison_expr __ "AND"i __ right:and_expr {
      return buildBinaryExpr('AND', left, right);
    }
  / comparison_expr

comparison_expr
  = between_expr
  / not_between_expr
  / in_expr
  / not_in_expr
  / left:additive_expr __ op:comparison_op __ right:comparison_expr {
      return buildBinaryExpr(op, left, right);
    }
  / additive_expr

comparison_op
  = ">=" { return '>='; }
  / "<=" { return '<='; }
  / "<>" { return '<>'; }
  / "!=" { return '!='; }
  / ">" { return '>'; }
  / "<" { return '<'; }
  / "=" { return '='; }
  / "LIKE"i { return 'LIKE'; }
  / "NOT"i ___ "LIKE"i { return 'NOT LIKE'; }
  / "IS"i ___ "NOT"i { return 'IS NOT'; }
  / "IS"i { return 'IS'; }

additive_expr
  = left:multiplicative_expr __ op:("+" / "-" !"-") __ right:additive_expr {
      const opStr = typeof op === 'string' ? op : op[0];
      return buildBinaryExpr(opStr, left, right);
    }
  / multiplicative_expr

multiplicative_expr
  = left:primary_expr __ op:("*" / "/" / "%") __ right:multiplicative_expr {
      return buildBinaryExpr(op, left, right);
    }
  / primary_expr

between_expr
  = left:additive_expr ___ "BETWEEN"i ___ low:additive_expr ___ "AND"i ___ high:additive_expr {
      return {
        type: 'binary_expr',
        operator: 'BETWEEN',
        left: left,
        right: { type: 'expr_list', value: [low, high] }
      };
    }

not_between_expr
  = left:additive_expr ___ "NOT"i ___ "BETWEEN"i ___ low:additive_expr ___ "AND"i ___ high:additive_expr {
      return {
        type: 'binary_expr',
        operator: 'NOT BETWEEN',
        left: left,
        right: { type: 'expr_list', value: [low, high] }
      };
    }

in_expr
  = left:additive_expr ___ "IN"i __ "(" __ head:expr tail:(__ "," __ expr)* __ ")" {
      return {
        type: 'binary_expr',
        operator: 'IN',
        left: left,
        right: { type: 'expr_list', value: createList(head, tail) }
      };
    }

not_in_expr
  = left:additive_expr ___ "NOT"i ___ "IN"i __ "(" __ head:expr tail:(__ "," __ expr)* __ ")" {
      return {
        type: 'binary_expr',
        operator: 'NOT IN',
        left: left,
        right: { type: 'expr_list', value: createList(head, tail) }
      };
    }

// ─── PRIMARY EXPRESSIONS ───

primary_expr
  = "(" __ e:expr __ ")" { e.parentheses = true; return e; }
  / exists_expr
  / cast_expr
  / case_expr
  / aggr_func
  / func_call
  / unary_expr
  / column_ref
  / literal_value

// ─── EXISTS EXPRESSION ───

exists_expr
  = "EXISTS"i __ "(" __ s:union_stmt __ ")" {
      return { type: 'unary_expr', operator: 'EXISTS', expr: { ast: s } };
    }

// ─── CASE EXPRESSION ───

case_expr
  = "CASE"i ___ args:case_when_list ___ els:case_else? ___ "END"i {
      return {
        type: 'case',
        expr: null,
        args: els ? [...args, els] : args
      };
    }
  / "CASE"i ___ e:expr ___ args:case_when_list ___ els:case_else? ___ "END"i {
      return {
        type: 'case',
        expr: e,
        args: els ? [...args, els] : args
      };
    }

case_when_list
  = head:case_when tail:(___ case_when)* {
      return createList(head, tail, 1);
    }

case_when
  = "WHEN"i ___ cond:expr ___ "THEN"i ___ result:expr {
      return { type: 'when', cond: cond, result: result };
    }

case_else
  = "ELSE"i ___ result:expr {
      return { type: 'else', result: result };
    }

// ─── CAST EXPRESSION ───
// Supports chained :: casts

cast_expr
  = "CAST"i __ "(" __ e:expr ___ "AS"i ___ t:data_type __ ")" {
      return {
        type: 'cast',
        keyword: 'cast',
        expr: e,
        symbol: 'as',
        target: [t]
      };
    }
  / e:primary_no_cast targets:(__ "::" __ data_type)+ {
      const targetList = targets.map(function(t) { return t[3]; });
      return {
        type: 'cast',
        keyword: 'cast',
        expr: e,
        symbol: '::',
        target: targetList
      };
    }

primary_no_cast
  = "(" __ e:expr __ ")" { e.parentheses = true; return e; }
  / aggr_func
  / func_call
  / column_ref
  / literal_value

data_type
  = name:data_type_name __ "(" __ len:integer __ "," __ scale:integer __ ")" {
      return { dataType: name, length: len, scale: scale };
    }
  / name:data_type_name __ "(" __ len:integer __ ")" {
      return { dataType: name, length: len };
    }
  / name:data_type_name {
      return { dataType: name };
    }

data_type_name
  = "BIGINT"i { return 'BIGINT'; }
  / "INTEGER"i { return 'INTEGER'; }
  / "INT"i { return 'INT'; }
  / "SMALLINT"i { return 'SMALLINT'; }
  / "NUMERIC"i { return 'NUMERIC'; }
  / "DECIMAL"i { return 'DECIMAL'; }
  / "REAL"i { return 'REAL'; }
  / "FLOAT"i { return 'FLOAT'; }
  / "DOUBLE"i ___ "PRECISION"i { return 'DOUBLE PRECISION'; }
  / "BOOLEAN"i { return 'BOOLEAN'; }
  / "DATE"i { return 'DATE'; }
  / "TIMESTAMP"i { return 'TIMESTAMP'; }
  / "TIMESTAMPTZ"i { return 'TIMESTAMPTZ'; }
  / "VARCHAR"i { return 'VARCHAR'; }
  / "CHAR"i { return 'CHAR'; }
  / "TEXT"i { return 'TEXT'; }
  / "JSONB"i { return 'JSONB'; }
  / "JSON"i { return 'JSON'; }
  / "UUID"i { return 'UUID'; }
  / "BYTEA"i { return 'BYTEA'; }

// ─── AGGREGATE FUNCTIONS ───
// With OVER clause and window frame support

aggr_func
  = name:aggr_func_name __ "(" __ dist:("DISTINCT"i ___)? e:expr __ ")" __ over:over_clause? {
      return {
        type: 'aggr_func',
        name: name,
        args: {
          distinct: dist ? 'DISTINCT' : null,
          expr: e
        },
        over: over || null
      };
    }
  / name:aggr_func_name __ "(" __ "*" __ ")" __ over:over_clause? {
      return {
        type: 'aggr_func',
        name: name,
        args: {
          distinct: null,
          expr: { type: 'star', value: '*' }
        },
        over: over || null
      };
    }

over_clause
  = "OVER"i __ "(" __ parts:over_parts __ ")" {
      return parts;
    }

over_parts
  = pb:partition_by? __ ob:order_by_clause? __ wf:window_frame? {
      return {
        partitionby: pb || null,
        orderby: ob || null,
        window_frame_clause: wf || null
      };
    }

partition_by
  = "PARTITION"i ___ "BY"i ___ head:expr tail:(__ "," __ expr)* {
      return createList(head, tail).map(function(e) { return { expr: e }; });
    }

window_frame
  = ft:frame_type ___ "BETWEEN"i ___ s:frame_bound ___ "AND"i ___ e:frame_bound {
      return ft + ' BETWEEN ' + s + ' AND ' + e;
    }
  / ft:frame_type ___ b:frame_bound {
      return ft + ' ' + b;
    }

frame_type
  = "ROWS"i { return 'ROWS'; }
  / "RANGE"i { return 'RANGE'; }

frame_bound
  = "UNBOUNDED"i ___ "PRECEDING"i { return 'UNBOUNDED PRECEDING'; }
  / "UNBOUNDED"i ___ "FOLLOWING"i { return 'UNBOUNDED FOLLOWING'; }
  / "CURRENT"i ___ "ROW"i { return 'CURRENT ROW'; }
  / n:integer ___ "PRECEDING"i { return n + ' PRECEDING'; }
  / n:integer ___ "FOLLOWING"i { return n + ' FOLLOWING'; }

aggr_func_name
  = "COUNT"i { return 'COUNT'; }
  / "SUM"i { return 'SUM'; }
  / "AVG"i { return 'AVG'; }
  / "MIN"i { return 'MIN'; }
  / "MAX"i { return 'MAX'; }
  / "ROW_NUMBER"i { return 'ROW_NUMBER'; }
  / "RANK"i { return 'RANK'; }
  / "DENSE_RANK"i { return 'DENSE_RANK'; }
  / "LEAD"i { return 'LEAD'; }
  / "LAG"i { return 'LAG'; }

// ─── FUNCTION CALLS ───

func_call
  = schema:ident_name "." name:ident_name __ "(" __ args:func_args? __ ")" {
      return {
        type: 'function',
        name: { schema: { type: 'default', value: schema }, name: [{ type: 'default', value: name }] },
        args: args ? { value: args } : null
      };
    }
  / name:ident_name __ "(" __ args:func_args? __ ")" {
      return {
        type: 'function',
        name: { name: [{ type: 'default', value: name }] },
        args: args ? { value: args } : null
      };
    }

func_args
  = head:expr tail:(__ "," __ expr)* {
      return createList(head, tail);
    }

// ─── UNARY EXPRESSION ───

unary_expr
  = "NOT"i ___ e:primary_expr {
      return { type: 'unary_expr', operator: 'NOT', expr: e };
    }
  / "-" e:primary_expr {
      return { type: 'unary_expr', operator: '-', expr: e };
    }

// ─── COLUMN REFERENCE ───

column_ref
  = schema:ident_name "." tbl:ident_name "." col:column_name {
      return { type: 'column_ref', schema: schema, table: tbl, column: col };
    }
  / tbl:ident_name "." col:column_name {
      return { type: 'column_ref', table: tbl, column: col };
    }
  / col:column_name !("(") {
      return { type: 'column_ref', table: null, column: col };
    }

column_name
  = "*" { return '*'; }
  / ident_name

// ─── LITERAL VALUES ───

literal_value
  = literal_string
  / literal_number
  / literal_null
  / literal_boolean
  / star_value

literal_string
  = "'" chars:[^']* "'" { return { type: 'single_quote_string', value: chars.join('') }; }

literal_number
  = digits:$([0-9]+ ("." [0-9]+)?) { return { type: 'number', value: parseFloat(digits) }; }

integer
  = digits:$[0-9]+ { return parseInt(digits, 10); }

literal_null
  = "NULL"i { return { type: 'null', value: null }; }

literal_boolean
  = "TRUE"i { return { type: 'boolean', value: true }; }
  / "FALSE"i { return { type: 'boolean', value: false }; }

star_value
  = "*" { return { type: 'star', value: '*' }; }

// ─── IDENTIFIERS ───

ident_name
  = "`" chars:[^`]+ "`" { return chars.join(''); }
  / "\"" chars:[^"]+ "\"" { return chars.join(''); }
  / !reserved_word name:$([a-zA-Z_] [a-zA-Z0-9_]*) { return name; }

reserved_word
  = ("SELECT"i / "FROM"i / "WHERE"i / "AND"i / "OR"i / "NOT"i / "IN"i / "BETWEEN"i
    / "ORDER"i / "BY"i / "GROUP"i / "HAVING"i / "LIMIT"i / "OFFSET"i / "AS"i
    / "JOIN"i / "INNER"i / "LEFT"i / "RIGHT"i / "FULL"i / "OUTER"i / "CROSS"i / "ON"i
    / "UNION"i / "INTERSECT"i / "EXCEPT"i / "ALL"i / "DISTINCT"i
    / "CASE"i / "WHEN"i / "THEN"i / "ELSE"i / "END"i
    / "CAST"i / "IS"i / "LIKE"i / "NULL"i / "TRUE"i / "FALSE"i
    / "WITH"i / "RECURSIVE"i / "USING"i / "ASC"i / "DESC"i / "NULLS"i
    / "OVER"i / "PARTITION"i / "ROWS"i / "RANGE"i / "EXISTS"i
    ) !([a-zA-Z0-9_])

// ─── WHITESPACE ───

__ "optional whitespace"
  = [ \t\n\r]*

___ "required whitespace"
  = [ \t\n\r]+
