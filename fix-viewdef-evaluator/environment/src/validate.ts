
import { fhirpathValidate } from './fhirpath-helper';

export function validate(viewDef: any, forTest: boolean = true): { errors: any[] } {
  const errors: any[] = [];

  if (!viewDef || typeof viewDef !== 'object') {
    errors.push({ message: 'ViewDefinition must be an object' });
    return { errors };
  }

  if (!viewDef.resource || typeof viewDef.resource !== 'string' || viewDef.resource.length === 0) {
    errors.push({ message: 'Missing or invalid "resource" field' });
  }

  if (!viewDef.select || !Array.isArray(viewDef.select) || viewDef.select.length === 0) {
    errors.push({ message: 'Missing or invalid "select" field' });
  }

  if (viewDef.constant && Array.isArray(viewDef.constant)) {
    for (const c of viewDef.constant) {
      if (!c.name) {
        errors.push({ message: 'Constant missing "name"' });
      }
      const hasValue = Object.keys(c).some((k: string) => k.startsWith('value'));
      if (!hasValue) {
        errors.push({ message: `Constant "${c.name || '?'}" is missing a value` });
      }
    }
  }

  function validateSelectExprs(exprs: any[]): void {
    if (!Array.isArray(exprs)) return;
    for (const expr of exprs) {
      if (expr.forEach !== undefined) {
        if (typeof expr.forEach !== 'string') {
          errors.push({ message: 'forEach must be a string' });
        } else if (!fhirpathValidate(expr.forEach)) {
          errors.push({ message: `Invalid FHIRPath in forEach: "${expr.forEach}"` });
        }
      }
      if (expr.forEachOrNull !== undefined) {
        if (typeof expr.forEachOrNull !== 'string') {
          errors.push({ message: 'forEachOrNull must be a string' });
        } else if (!fhirpathValidate(expr.forEachOrNull)) {
          errors.push({ message: `Invalid FHIRPath in forEachOrNull: "${expr.forEachOrNull}"` });
        }
      }
      if (expr.repeat !== undefined) {
        if (!Array.isArray(expr.repeat)) {
          errors.push({ message: 'repeat must be an array of strings' });
        } else {
          for (const rp of expr.repeat) {
            if (typeof rp !== 'string') {
              errors.push({ message: 'repeat paths must be strings' });
            } else if (!fhirpathValidate(rp)) {
              errors.push({ message: `Invalid FHIRPath in repeat: "${rp}"` });
            }
          }
        }
      }
      if (expr.column && Array.isArray(expr.column)) {
        for (const col of expr.column) {
          if (col.path && typeof col.path === 'string') {
            if (!fhirpathValidate(col.path)) {
              errors.push({ message: `Invalid FHIRPath in column path: "${col.path}"` });
            }
          }
          if (forTest && (!col.name || !col.path || !col.type)) {
            errors.push({ message: `Column missing required fields (name, path, type)` });
          }
        }
      }
      if (expr.select) validateSelectExprs(expr.select);
      if (expr.unionAll) validateSelectExprs(expr.unionAll);
    }
  }

  if (viewDef.select) {
    validateSelectExprs(viewDef.select);
  }

  if (viewDef.where && Array.isArray(viewDef.where)) {
    for (const w of viewDef.where) {
      if (w.path && typeof w.path === 'string') {
        if (!fhirpathValidate(w.path)) {
          errors.push({ message: `Invalid FHIRPath in where: "${w.path}"` });
        }
      }
    }
  }

  return { errors };
}
