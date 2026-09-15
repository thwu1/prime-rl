// Test runner for SQL dialect transpiler
// Tests three layers: parser (grammar), stringifier (AST→SQL), and transpiler (parse→transform→stringify)
//

const fs = require('fs');

let sqlify, parse, transpile, transformAST;
try {
  const mod = require('/app/dist/index');
  sqlify = mod.sqlify;
  parse = mod.parse;
  transpile = mod.transpile;
  transformAST = mod.transformAST;
} catch (e) {
  const failResult = {
    results: [{
      title: 'module_load',
      passed: false,
      expected: 'module loads successfully',
      actual: 'ERROR: ' + e.message
    }],
    total: 1, passed: 0, failed: 1
  };
  fs.writeFileSync('/tmp/transpiler_test_results.json', JSON.stringify(failResult, null, 2));
  process.exit(1);
}

// ─── Helpers for AST-based tests ───

function colRef(column, table) {
  return { type: 'column_ref', table: table || null, column: column };
}
function num(n) { return { type: 'number', value: n }; }
function str(s) { return { type: 'single_quote_string', value: s }; }
function star() { return { type: 'star', value: '*' }; }
function col(expr, alias) { return { expr: expr, as: alias || null }; }
function tbl(name, alias, db) { return { db: db || null, table: name, as: alias || null }; }
function stmtDefaults(overrides) {
  return Object.assign({
    type: 'select', with: null, recursive: false, options: null, distinct: null,
    columns: [], from: null, where: null, groupby: null, having: null,
    orderby: null, limit: null,
  }, overrides);
}

const testCases = [];

// ════════════════════════════════════════════════════════════════
// SECTION A: Stringifier tests (AST → SQL)
// ════════════════════════════════════════════════════════════════

// A1. MySQL identifier quoting
testCases.push({
  title: 'stringify_mysql_quoting',
  type: 'stringify',
  dialect: 'mysql',
  ast: stmtDefaults({
    columns: [col(colRef('id')), col(colRef('name'))],
    from: [tbl('users')],
  }),
  expected: 'SELECT `id`, `name` FROM `users`'
});

// A2. PostgreSQL identifier quoting
testCases.push({
  title: 'stringify_pg_quoting',
  type: 'stringify',
  dialect: 'postgresql',
  ast: stmtDefaults({
    columns: [col(colRef('id')), col(colRef('name'))],
    from: [tbl('users')],
  }),
  expected: 'SELECT "id", "name" FROM "users"'
});

// A3. Snowflake identifier quoting
testCases.push({
  title: 'stringify_snowflake_quoting',
  type: 'stringify',
  dialect: 'snowflake',
  ast: stmtDefaults({
    columns: [col(colRef('name'))],
    from: [tbl('accounts')],
  }),
  expected: 'SELECT "name" FROM "accounts"'
});

// A4. BETWEEN expression
testCases.push({
  title: 'stringify_between',
  type: 'stringify',
  dialect: 'mysql',
  ast: stmtDefaults({
    columns: [col(star())],
    from: [tbl('products')],
    where: {
      type: 'binary_expr', operator: 'BETWEEN',
      left: colRef('price'),
      right: { type: 'expr_list', value: [num(10), num(100)] }
    },
  }),
  expected: 'SELECT * FROM `products` WHERE `price` BETWEEN 10 AND 100'
});

// A5. IN expression
testCases.push({
  title: 'stringify_in',
  type: 'stringify',
  dialect: 'mysql',
  ast: stmtDefaults({
    columns: [col(num(1))],
    where: {
      type: 'binary_expr', operator: 'IN',
      left: colRef('status'),
      right: { type: 'expr_list', value: [str('active'), str('pending')] }
    },
  }),
  expected: "SELECT 1 WHERE `status` IN ('active', 'pending')"
});

// A6. CASE with ELSE
testCases.push({
  title: 'stringify_case_else',
  type: 'stringify',
  dialect: 'mysql',
  ast: stmtDefaults({
    columns: [col({
      type: 'case', expr: null,
      args: [
        { type: 'when', cond: { type: 'binary_expr', operator: '>', left: colRef('x'), right: num(0) }, result: str('pos') },
        { type: 'else', result: str('neg') }
      ]
    }, 'label')],
    from: [tbl('data')],
  }),
  expected: "SELECT CASE WHEN `x` > 0 THEN 'pos' ELSE 'neg' END AS `label` FROM `data`"
});

// A7. COUNT(DISTINCT ...)
testCases.push({
  title: 'stringify_count_distinct',
  type: 'stringify',
  dialect: 'mysql',
  ast: stmtDefaults({
    columns: [col({
      type: 'aggr_func', name: 'COUNT',
      args: { distinct: 'DISTINCT', expr: colRef('user_id') }
    })],
    from: [tbl('orders')],
  }),
  expected: 'SELECT COUNT(DISTINCT `user_id`) FROM `orders`'
});

// A8. SUM with OVER (PARTITION BY)
testCases.push({
  title: 'stringify_sum_over_partition',
  type: 'stringify',
  dialect: 'mysql',
  ast: stmtDefaults({
    columns: [col({
      type: 'aggr_func', name: 'SUM',
      args: { distinct: null, expr: colRef('amount') },
      over: {
        partitionby: [{ expr: colRef('dept') }],
        orderby: null, window_frame_clause: null
      }
    }, 'total')],
    from: [tbl('sales')],
  }),
  expected: 'SELECT SUM(`amount`) OVER (PARTITION BY `dept`) AS `total` FROM `sales`'
});

// A9. GROUP BY + HAVING
testCases.push({
  title: 'stringify_group_having',
  type: 'stringify',
  dialect: 'mysql',
  ast: stmtDefaults({
    columns: [col(colRef('dept')), col({ type: 'aggr_func', name: 'COUNT', args: { distinct: null, expr: star() } }, 'cnt')],
    from: [tbl('employees')],
    groupby: { columns: [colRef('dept')] },
    having: { type: 'binary_expr', operator: '>', left: { type: 'aggr_func', name: 'COUNT', args: { distinct: null, expr: star() } }, right: num(5) },
  }),
  expected: 'SELECT `dept`, COUNT(*) AS `cnt` FROM `employees` GROUP BY `dept` HAVING COUNT(*) > 5'
});

// A10. WITH RECURSIVE
testCases.push({
  title: 'stringify_recursive_cte',
  type: 'stringify',
  dialect: 'mysql',
  ast: stmtDefaults({
    with: [{ name: { value: 'tree' }, stmt: { ast: stmtDefaults({ columns: [col(colRef('id'))], from: [tbl('nodes')] }) } }],
    recursive: true,
    columns: [col(star())],
    from: [tbl('tree')],
  }),
  expected: 'WITH RECURSIVE `tree` AS (SELECT `id` FROM `nodes`) SELECT * FROM `tree`'
});

// A11. INNER JOIN with ON
testCases.push({
  title: 'stringify_join_on',
  type: 'stringify',
  dialect: 'mysql',
  ast: stmtDefaults({
    columns: [col(colRef('id', 'u'))],
    from: [
      tbl('users', 'u'),
      { db: null, table: 'orders', as: 'o', join: 'INNER JOIN',
        on: { type: 'binary_expr', operator: '=', left: colRef('id', 'u'), right: colRef('user_id', 'o') } }
    ],
  }),
  expected: 'SELECT `u`.`id` FROM `users` AS `u` INNER JOIN `orders` AS `o` ON `u`.`id` = `o`.`user_id`'
});

// A12. UNION
testCases.push({
  title: 'stringify_union',
  type: 'stringify',
  dialect: 'mysql',
  ast: Object.assign(stmtDefaults({
    _parentheses: true, columns: [col(colRef('a'))], from: [tbl('t1')],
  }), {
    set_op: 'UNION',
    _next: stmtDefaults({ _parentheses: true, columns: [col(colRef('b'))], from: [tbl('t2')] })
  }),
  expected: '(SELECT `a` FROM `t1`) UNION (SELECT `b` FROM `t2`)'
});

// A13. ORDER BY with NULLS LAST
testCases.push({
  title: 'stringify_order_nulls',
  type: 'stringify',
  dialect: 'mysql',
  ast: stmtDefaults({
    columns: [col(star())], from: [tbl('items')],
    orderby: [{ expr: colRef('price'), type: 'ASC', nulls: 'NULLS LAST' }],
  }),
  expected: 'SELECT * FROM `items` ORDER BY `price` ASC NULLS LAST'
});

// A14. LIMIT with OFFSET
testCases.push({
  title: 'stringify_limit_offset',
  type: 'stringify',
  dialect: 'mysql',
  ast: stmtDefaults({
    columns: [col(star())], from: [tbl('items')],
    limit: { separator: 'offset', value: [num(10), num(20)] },
  }),
  expected: 'SELECT * FROM `items` LIMIT 10 OFFSET 20'
});

// A15. PostgreSQL :: cast
testCases.push({
  title: 'stringify_pg_double_colon',
  type: 'stringify',
  dialect: 'postgresql',
  ast: stmtDefaults({
    columns: [col({
      type: 'cast', keyword: 'cast', expr: colRef('val'),
      symbol: '::', target: [{ dataType: 'INTEGER' }]
    })],
    from: [tbl('t')],
  }),
  expected: 'SELECT "val"::INTEGER FROM "t"'
});

// A16. Chained :: cast
testCases.push({
  title: 'stringify_chained_cast',
  type: 'stringify',
  dialect: 'postgresql',
  ast: stmtDefaults({
    columns: [col({
      type: 'cast', keyword: 'cast', expr: colRef('data'),
      symbol: '::', target: [{ dataType: 'TEXT' }, { dataType: 'INTEGER' }]
    })],
    from: [tbl('t')],
  }),
  expected: 'SELECT "data"::TEXT::INTEGER FROM "t"'
});

// A17. ROW_NUMBER OVER (PARTITION BY ... ORDER BY ...)
testCases.push({
  title: 'stringify_rownum_over',
  type: 'stringify',
  dialect: 'mysql',
  ast: stmtDefaults({
    columns: [col({
      type: 'aggr_func', name: 'ROW_NUMBER',
      args: { distinct: null, expr: star() },
      over: {
        partitionby: [{ expr: colRef('dept') }],
        orderby: [{ expr: colRef('salary'), type: 'DESC' }],
        window_frame_clause: null
      }
    }, 'rn')],
    from: [tbl('employees')],
  }),
  expected: 'SELECT ROW_NUMBER(*) OVER (PARTITION BY `dept` ORDER BY `salary` DESC) AS `rn` FROM `employees`'
});

// A18. EXISTS subquery expression
testCases.push({
  title: 'stringify_exists',
  type: 'stringify',
  dialect: 'mysql',
  ast: stmtDefaults({
    columns: [col(star())],
    from: [tbl('users')],
    where: {
      type: 'unary_expr',
      operator: 'EXISTS',
      expr: { ast: stmtDefaults({
        columns: [col(num(1))],
        from: [tbl('orders')],
        where: { type: 'binary_expr', operator: '=', left: colRef('user_id', 'orders'), right: colRef('id', 'users') }
      })}
    }
  }),
  expected: 'SELECT * FROM `users` WHERE EXISTS (SELECT 1 FROM `orders` WHERE `orders`.`user_id` = `users`.`id`)'
});

// A19. Window frame clause
testCases.push({
  title: 'stringify_window_frame',
  type: 'stringify',
  dialect: 'mysql',
  ast: stmtDefaults({
    columns: [col({
      type: 'aggr_func', name: 'SUM',
      args: { distinct: null, expr: colRef('amount') },
      over: {
        partitionby: null,
        orderby: [{ expr: colRef('ts'), type: 'ASC' }],
        window_frame_clause: 'ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW'
      }
    }, 'running_total')],
    from: [tbl('transactions')],
  }),
  expected: 'SELECT SUM(`amount`) OVER (ORDER BY `ts` ASC ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS `running_total` FROM `transactions`'
});

// ════════════════════════════════════════════════════════════════
// SECTION B: Parser round-trip tests (SQL → parse → stringify → compare)
// ════════════════════════════════════════════════════════════════

// B1. Simple SELECT round-trip
testCases.push({
  title: 'parse_roundtrip_simple',
  type: 'roundtrip',
  inputSQL: 'SELECT id, name FROM users',
  dialect: 'mysql',
  expected: 'SELECT `id`, `name` FROM `users`'
});

// B2. WHERE with comparison
testCases.push({
  title: 'parse_roundtrip_where',
  type: 'roundtrip',
  inputSQL: 'SELECT * FROM users WHERE age > 18',
  dialect: 'mysql',
  expected: 'SELECT * FROM `users` WHERE `age` > 18'
});

// B3. WHERE with AND (tests operator precedence)
testCases.push({
  title: 'parse_roundtrip_where_and',
  type: 'roundtrip',
  inputSQL: 'SELECT * FROM users WHERE age > 18 AND active = 1',
  dialect: 'mysql',
  expected: 'SELECT * FROM `users` WHERE `age` > 18 AND `active` = 1'
});

// B4. BETWEEN round-trip
testCases.push({
  title: 'parse_roundtrip_between',
  type: 'roundtrip',
  inputSQL: 'SELECT * FROM products WHERE price BETWEEN 10 AND 100',
  dialect: 'mysql',
  expected: 'SELECT * FROM `products` WHERE `price` BETWEEN 10 AND 100'
});

// B5. CASE WHEN ELSE round-trip
testCases.push({
  title: 'parse_roundtrip_case',
  type: 'roundtrip',
  inputSQL: "SELECT CASE WHEN x > 0 THEN 'pos' ELSE 'neg' END AS label FROM t",
  dialect: 'mysql',
  expected: "SELECT CASE WHEN `x` > 0 THEN 'pos' ELSE 'neg' END AS `label` FROM `t`"
});

// B6. Aggregate with window function round-trip
testCases.push({
  title: 'parse_roundtrip_window',
  type: 'roundtrip',
  inputSQL: 'SELECT SUM(amount) OVER (PARTITION BY dept) AS total FROM sales',
  dialect: 'mysql',
  expected: 'SELECT SUM(`amount`) OVER (PARTITION BY `dept`) AS `total` FROM `sales`'
});

// B7. PostgreSQL :: cast round-trip
testCases.push({
  title: 'parse_roundtrip_pg_cast',
  type: 'roundtrip',
  inputSQL: 'SELECT val::INTEGER FROM t',
  dialect: 'postgresql',
  expected: 'SELECT "val"::INTEGER FROM "t"'
});

// B8. Chained :: cast round-trip
testCases.push({
  title: 'parse_roundtrip_chained_cast',
  type: 'roundtrip',
  inputSQL: 'SELECT data::TEXT::INTEGER FROM t',
  dialect: 'postgresql',
  expected: 'SELECT "data"::TEXT::INTEGER FROM "t"'
});

// B9. JOIN with ON round-trip
testCases.push({
  title: 'parse_roundtrip_join',
  type: 'roundtrip',
  inputSQL: 'SELECT u.id FROM users AS u INNER JOIN orders AS o ON u.id = o.user_id',
  dialect: 'mysql',
  expected: 'SELECT `u`.`id` FROM `users` AS `u` INNER JOIN `orders` AS `o` ON `u`.`id` = `o`.`user_id`'
});

// B10. UNION round-trip
testCases.push({
  title: 'parse_roundtrip_union',
  type: 'roundtrip',
  inputSQL: '(SELECT a FROM t1) UNION (SELECT b FROM t2)',
  dialect: 'mysql',
  expected: '(SELECT `a` FROM `t1`) UNION (SELECT `b` FROM `t2`)'
});

// B11. ORDER BY with NULLS LAST round-trip
testCases.push({
  title: 'parse_roundtrip_nulls_last',
  type: 'roundtrip',
  inputSQL: 'SELECT * FROM items ORDER BY price ASC NULLS LAST',
  dialect: 'mysql',
  expected: 'SELECT * FROM `items` ORDER BY `price` ASC NULLS LAST'
});

// B12. GROUP BY + HAVING round-trip
testCases.push({
  title: 'parse_roundtrip_having',
  type: 'roundtrip',
  inputSQL: 'SELECT dept, COUNT(*) AS cnt FROM employees GROUP BY dept HAVING COUNT(*) > 5',
  dialect: 'mysql',
  expected: 'SELECT `dept`, COUNT(*) AS `cnt` FROM `employees` GROUP BY `dept` HAVING COUNT(*) > 5'
});

// B13. WITH RECURSIVE round-trip
testCases.push({
  title: 'parse_roundtrip_recursive_cte',
  type: 'roundtrip',
  inputSQL: 'WITH RECURSIVE tree AS (SELECT id FROM nodes) SELECT * FROM tree',
  dialect: 'mysql',
  expected: 'WITH RECURSIVE `tree` AS (SELECT `id` FROM `nodes`) SELECT * FROM `tree`'
});

// B14. EXISTS subquery round-trip
testCases.push({
  title: 'parse_roundtrip_exists',
  type: 'roundtrip',
  inputSQL: 'SELECT * FROM users WHERE EXISTS (SELECT 1 FROM orders WHERE orders.user_id = users.id)',
  dialect: 'mysql',
  expected: 'SELECT * FROM `users` WHERE EXISTS (SELECT 1 FROM `orders` WHERE `orders`.`user_id` = `users`.`id`)'
});

// B15. NOT IN round-trip
testCases.push({
  title: 'parse_roundtrip_not_in',
  type: 'roundtrip',
  inputSQL: "SELECT * FROM t WHERE status NOT IN ('closed', 'archived')",
  dialect: 'mysql',
  expected: "SELECT * FROM `t` WHERE `status` NOT IN ('closed', 'archived')"
});

// B16. CAST with AS and precision round-trip
testCases.push({
  title: 'parse_roundtrip_cast_as',
  type: 'roundtrip',
  inputSQL: 'SELECT CAST(price AS NUMERIC(10, 2)) FROM products',
  dialect: 'mysql',
  expected: 'SELECT CAST(`price` AS NUMERIC(10, 2)) FROM `products`'
});

// B17. Window frame clause round-trip
testCases.push({
  title: 'parse_roundtrip_window_frame',
  type: 'roundtrip',
  inputSQL: 'SELECT SUM(amount) OVER (ORDER BY ts ASC ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS running_total FROM transactions',
  dialect: 'mysql',
  expected: 'SELECT SUM(`amount`) OVER (ORDER BY `ts` ASC ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS `running_total` FROM `transactions`'
});

// ════════════════════════════════════════════════════════════════
// SECTION C: Cross-dialect transpilation tests
// ════════════════════════════════════════════════════════════════

// C1. MySQL → PostgreSQL basic transpile (identifier quoting changes)
testCases.push({
  title: 'transpile_mysql_to_pg_basic',
  type: 'transpile',
  inputSQL: 'SELECT id, name FROM users WHERE age > 21',
  sourceDialect: 'mysql',
  targetDialect: 'postgresql',
  expected: 'SELECT "id", "name" FROM "users" WHERE "age" > 21'
});

// C2. MySQL → PostgreSQL with IFNULL → COALESCE
testCases.push({
  title: 'transpile_mysql_to_pg_ifnull',
  type: 'transpile',
  inputSQL: "SELECT IFNULL(name, 'unknown') FROM users",
  sourceDialect: 'mysql',
  targetDialect: 'postgresql',
  expected: "SELECT COALESCE(\"name\", 'unknown') FROM \"users\""
});

// C3. PostgreSQL → MySQL cast transformation (:: → CAST)
testCases.push({
  title: 'transpile_pg_to_mysql_cast',
  type: 'transpile',
  inputSQL: 'SELECT val::INTEGER FROM t',
  sourceDialect: 'postgresql',
  targetDialect: 'mysql',
  expected: 'SELECT CAST(`val` AS INTEGER) FROM `t`'
});

// C4. PostgreSQL → MySQL (STRING_AGG → GROUP_CONCAT)
testCases.push({
  title: 'transpile_pg_to_mysql_string_agg',
  type: 'transpile',
  inputSQL: "SELECT STRING_AGG(name, ', ') FROM users",
  sourceDialect: 'postgresql',
  targetDialect: 'mysql',
  expected: "SELECT GROUP_CONCAT(`name`, ', ') FROM `users`"
});

// C5. PostgreSQL → MySQL chained :: cast → nested CAST
testCases.push({
  title: 'transpile_pg_to_mysql_chained_cast',
  type: 'transpile',
  inputSQL: 'SELECT data::TEXT::VARCHAR FROM t',
  sourceDialect: 'postgresql',
  targetDialect: 'mysql',
  expected: 'SELECT CAST(CAST(`data` AS TEXT) AS VARCHAR) FROM `t`'
});

// C6. MySQL → Snowflake (quoting change)
testCases.push({
  title: 'transpile_mysql_to_snowflake',
  type: 'transpile',
  inputSQL: 'SELECT id, name FROM users WHERE active = TRUE',
  sourceDialect: 'mysql',
  targetDialect: 'snowflake',
  expected: 'SELECT "id", "name" FROM "users" WHERE "active" = TRUE'
});

// ──────────────────────────────────────────────────────────────
// Run all tests
// ──────────────────────────────────────────────────────────────

const results = testCases.map(tc => {
  try {
    let actual;
    if (tc.type === 'stringify') {
      actual = sqlify(tc.ast, { dialect: tc.dialect });
    } else if (tc.type === 'roundtrip') {
      const ast = parse(tc.inputSQL);
      actual = sqlify(ast, { dialect: tc.dialect });
    } else if (tc.type === 'transpile') {
      actual = transpile(tc.inputSQL, {
        sourceDialect: tc.sourceDialect,
        targetDialect: tc.targetDialect
      });
    }
    return {
      title: tc.title,
      passed: actual === tc.expected,
      expected: tc.expected,
      actual: actual
    };
  } catch (err) {
    return {
      title: tc.title,
      passed: false,
      expected: tc.expected,
      actual: 'ERROR: ' + (err.message || String(err))
    };
  }
});

const passedCount = results.filter(r => r.passed).length;
const failedCount = results.filter(r => !r.passed).length;

const output = { results, total: results.length, passed: passedCount, failed: failedCount };
fs.writeFileSync('/tmp/transpiler_test_results.json', JSON.stringify(output, null, 2));

console.log(`\nTest Results: ${passedCount}/${results.length} passed`);
if (failedCount > 0) {
  console.log('\nFailures:');
  results.filter(r => !r.passed).forEach(r => {
    console.log(`  FAIL: ${r.title}`);
    console.log(`    expected: ${r.expected}`);
    console.log(`    actual:   ${r.actual}`);
  });
}

process.exit(failedCount > 0 ? 1 : 0);
