/**
 * SQL AST Type Definitions
 *
 * Describes the shapes of AST nodes that the stringifier converts to SQL.
 *
 * Expression node types (dispatched by expr.ts):
 *   column_ref   – { type, table, column, schema?, db? }
 *   binary_expr  – { type, operator, left, right, parentheses? }
 *   aggr_func    – { type, name, args: { expr, distinct?, orderby? }, over?, filter?, within_group? }
 *   function     – { type, name: { name: ValueExpr[] }, args?, over?, within_group? }
 *   cast         – { type, keyword, expr, symbol ('as'|'::'), target: CastTarget[] }
 *   case         – { type, expr, args: (CaseWhen|CaseElse)[] }
 *   unary_expr   – { type, operator, expr, parentheses? }
 *   expr_list    – { type, value: Expr[], parentheses?, separator? }
 *   number/string/single_quote_string/null/boolean/… – literal value nodes
 *   select       – sub-query (same shape as top-level SelectAST)
 *
 * Statement-level nodes (dispatched by union.ts → select.ts):
 *   SelectAST    – with?, distinct?, columns, from?, where?, groupby?,
 *                  having?, orderby?, limit?, _next?, set_op?, …
 *
 * WITH clause:
 *   WithClause   – { name, stmt: { ast: SelectAST }, recursive?, columns? }
 *
 * Window / OVER:
 *   WindowSpec   – { partitionby?, orderby?, window_frame_clause? }
 *   WindowFrame  – { type ('ROWS'|'RANGE'|'GROUPS'), start: FrameBound, end?: FrameBound }
 *   FrameBound   – { type ('UNBOUNDED PRECEDING'|'CURRENT ROW'|'PRECEDING'|'FOLLOWING'), value? }
 *
 * ORDER BY item:
 *   OrderByItem  – { expr, type ('ASC'|'DESC'), nulls? ('NULLS FIRST'|'NULLS LAST') }
 *
 * DISTINCT ON (PostgreSQL):
 *   DistinctOn   – { type: 'DISTINCT', columns: Expr[] }
 *
 * FILTER clause (aggregate):
 *   FilterClause – { where: Expr }
 *
 * FROM / table references:
 *   TableRef     – { db?, schema?, table, as?, join?, on?, using?, expr?, type?, lateral? }
 */


export interface WithClause {
  name: { type: string; value: string } | string;
  stmt: { ast: any } | any;
  columns?: any[];
  recursive?: boolean;
}

export interface OrderByItem {
  expr: any;
  type: string;
  nulls?: string | null;
}

export interface ColumnItem {
  expr: any;
  as: string | { type: string; value: string } | null;
}

export interface FilterClause {
  where: any;
}

export interface TableRef {
  db: string | null;
  table: string | null;
  as: string | null;
  schema?: string | null;
  join?: string;
  on?: any;
  using?: any[];
  expr?: any;
  type?: string;
  lateral?: boolean;
}

export interface WindowFrame {
  type: string;
  start: { type: string; value?: number | null };
  end?: { type: string; value?: number | null } | null;
}

export interface WindowSpec {
  partitionby?: any[] | null;
  orderby?: OrderByItem[] | null;
  window_frame_clause?: WindowFrame | string | null;
}

export interface GroupBy {
  columns: any[] | null;
  modifiers?: any[];
}

export interface LimitClause {
  seperator: string;
  value: any[];
}
