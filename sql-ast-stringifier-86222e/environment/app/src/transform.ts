// Dialect transformation module
// Transforms AST nodes to adapt SQL between dialects.

import { Dialect, TranspileOptions } from './types';

// Transform an AST from source dialect to target dialect
export function transformAST(ast: any, options: TranspileOptions): any {
  if (!ast) return ast;
  return walkAndTransform(JSON.parse(JSON.stringify(ast)), options);
}

function walkAndTransform(node: any, options: TranspileOptions): any {
  if (!node || typeof node !== 'object') return node;

  if (Array.isArray(node)) {
    return node.map(n => walkAndTransform(n, options));
  }

  if (node.type === 'function') {
    node = transformFunction(node, options);
  }

  if (node.type === 'cast') {
    node = transformCast(node, options);
  }

  for (const key of Object.keys(node)) {
    if (typeof node[key] === 'object' && node[key] !== null) {
      node[key] = walkAndTransform(node[key], options);
    }
  }

  return node;
}

function transformFunction(node: any, options: TranspileOptions): any {
  const { sourceDialect, targetDialect } = options;
  const funcName = node.name?.name?.[0]?.value;
  if (!funcName) return node;

  const upper = funcName.toUpperCase();

  if (sourceDialect === 'mysql' && targetDialect === 'postgresql') {
    if (upper === 'GROUP_CONCAT') {
      node.name.name[0].value = 'STRING_AGG';
    }
  }

  if (sourceDialect === 'postgresql' && targetDialect === 'mysql') {
    if (upper === 'STRING_AGG') {
      node.name.name[0].value = 'GROUP_CONCAT';
    }
  }

  return node;
}

function transformCast(node: any, options: TranspileOptions): any {
  const { targetDialect } = options;

  if (targetDialect === 'mysql' && node.symbol === '::') {
    return node;
  }

  return node;
}
