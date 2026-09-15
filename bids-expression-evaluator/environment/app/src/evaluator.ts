
import { ASTNode } from './types';
import { builtinFunctions } from './functions';

export type Context = Record<string, unknown>;

export function evaluate(node: ASTNode, context: Context): unknown {
  switch (node.type) {
    case 'NumberLiteral':
      return node.value;

    case 'StringLiteral':
      return node.value;

    case 'BooleanLiteral':
      return node.value;

    case 'NullLiteral':
      return null;

    case 'ArrayLiteral':
      return node.elements.map((el) => evaluate(el, context));

    case 'ObjectLiteral':
      return {};

    case 'Identifier': {
      const val = context[node.name];
      return val === undefined ? null : val;
    }

    case 'MemberAccess': {
      const obj = evaluate(node.object, context);
      if (typeof obj !== 'object' || obj === null) {
        throw new Error(`Cannot access property '${node.property}' of ${obj}`);
      }
      const val = (obj as Record<string, unknown>)[node.property];
      return val === undefined ? null : val;
    }

    case 'IndexAccess': {
      const obj = evaluate(node.object, context);
      const idx = evaluate(node.index, context);
      if (!Array.isArray(obj)) {
        throw new Error(`Cannot index into non-array value`);
      }
      return obj[idx as number];
    }

    case 'FunctionCall': {
      const fn = builtinFunctions[node.name];
      if (!fn) {
        throw new Error(`Unknown function: ${node.name}`);
      }
      const args = node.args.map((arg) => evaluate(arg, context));
      return fn(...args);
    }

    case 'UnaryOp': {
      const operand = evaluate(node.operand, context);
      switch (node.operator) {
        case '!':
          if (operand === null) return null;
          return !operand;
        case '-':
          return -(operand as number);
        default:
          throw new Error(`Unknown unary operator: ${node.operator}`);
      }
    }

    case 'BinaryOp': {
      if (node.operator === '&&') {
        const left = evaluate(node.left, context);
        if (!left) return false;
        return evaluate(node.right, context);
      }
      if (node.operator === '||') {
        const left = evaluate(node.left, context);
        if (left) return left;
        return evaluate(node.right, context);
      }

      const left = evaluate(node.left, context);
      const right = evaluate(node.right, context);

      switch (node.operator) {
        case '+':
          if (typeof left === 'string' || typeof right === 'string') {
            return String(left) + String(right);
          }
          return (left as number) + (right as number);
        case '-':
          return (left as number) - (right as number);
        case '*':
          return (left as number) * (right as number);
        case '/':
          return (left as number) / (right as number);
        case '%':
          return (left as number) % (right as number);
        case '==':
          return left === right;
        case '!=':
          return left !== right;
        case '<':
          return (left as number) < (right as number);
        case '<=':
          return (left as number) <= (right as number);
        case '>':
          return (left as number) > (right as number);
        case '>=':
          return (left as number) >= (right as number);
        default:
          throw new Error(`Unknown binary operator: ${node.operator}`);
      }
    }

    case 'InExpression': {
      const value = evaluate(node.value, context);
      const collection = evaluate(node.collection, context);
      if (collection === null) return null;
      if (typeof collection === 'object' && !Array.isArray(collection)) {
        return (value as string) in (collection as Record<string, unknown>);
      }
      if (Array.isArray(collection)) {
        return collection.includes(value);
      }
      return false;
    }

    default:
      throw new Error(`Unknown node type: ${(node as ASTNode).type}`);
  }
}
