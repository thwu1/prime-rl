// SQL AST Type Definitions for the dialect transpiler

export type Dialect = 'mysql' | 'postgresql' | 'snowflake';

export interface SqlifyOptions {
  dialect: Dialect;
}

export interface TranspileOptions {
  sourceDialect: Dialect;
  targetDialect: Dialect;
}

export interface ColumnRefNode {
  type: 'column_ref';
  table: string | null;
  column: string | { expr: any };
  schema?: string | null;
}

export interface BinaryExprNode {
  type: 'binary_expr';
  operator: string;
  left: any;
  right: any;
  parentheses?: boolean;
}

export interface UnaryExprNode {
  type: 'unary_expr';
  operator: string;
  expr: any;
  parentheses?: boolean;
}

export interface CaseNode {
  type: 'case';
  expr: any | null;
  args: Array<{ type: 'when'; cond: any; result: any } | { type: 'else'; result: any }>;
}

export interface AggrFuncNode {
  type: 'aggr_func';
  name: string;
  args: {
    expr: any;
    distinct: string | null;
  };
  over?: OverSpec | null;
}

export interface FunctionNode {
  type: 'function';
  name: { schema?: any; name: any[] };
  args?: any | null;
  over?: OverSpec | null;
}

export interface CastNode {
  type: 'cast';
  keyword: string;
  expr: any;
  symbol: 'as' | '::';
  target: CastTarget[];
}

export interface CastTarget {
  dataType: string;
  length?: number | null;
  scale?: number | null;
}

export interface OverSpec {
  partitionby?: any[] | null;
  orderby?: OrderByItem[] | null;
  window_frame_clause?: string | null;
}

export interface OrderByItem {
  expr: any;
  type?: string;
  nulls?: string;
}

export interface ExprListNode {
  type: 'expr_list';
  value: any[];
  parentheses?: boolean;
  separator?: string;
}

export interface LiteralNode {
  type: string;
  value: any;
  prefix?: string;
}

export interface WithItem {
  name: { value: string } | string;
  stmt: { ast: any } | any;
  columns?: string[] | null;
}

export interface FromItem {
  type?: string;
  db: string | null;
  table: string;
  schema?: string | null;
  as: string | null;
  join?: string;
  on?: any;
  using?: any[];
  expr?: { ast: any };
}

export interface LimitClause {
  separator: string;
  value: any[];
}

export interface GroupByClause {
  columns: any[] | null;
}

export interface SelectNode {
  type: 'select';
  with?: WithItem[] | null;
  recursive?: boolean;
  options?: string[] | null;
  distinct?: string | null;
  columns: any[] | '*';
  from?: FromItem[] | null;
  where?: any | null;
  groupby?: GroupByClause | null;
  having?: any | null;
  orderby?: OrderByItem[] | null;
  limit?: LimitClause | null;
  _next?: SelectNode;
  set_op?: string;
  _parentheses?: boolean;
  _orderby?: OrderByItem[] | null;
  _limit?: LimitClause | null;
  parentheses_symbol?: boolean;
}
