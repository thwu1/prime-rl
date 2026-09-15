// eslint-disable-next-line @typescript-eslint/no-var-requires
const fhirpath = require('fhirpath');
// eslint-disable-next-line @typescript-eslint/no-var-requires
const fhirpath_r4_model = require('fhirpath/fhir-context/r4');

const userInvocationTable = {
  identity: { fn: (nodes: any[]) => nodes, arity: { 0: [] } },
};

const fhirpathOptions = {
  userInvocationTable,
};

function rewritePath(path: string): string {
  // Handle $this → identity() to reference the current iteration context
  if (path === '$this') return 'identity()';
  if (path.startsWith('$this.')) {
    path = 'identity()' + path.slice(5);
  }

  // Handle ofType(X) → capitalize and merge with preceding path segment
  // e.g. value.ofType(string) → valueString
  // This is needed because fhirpath.js only resolves polymorphic types
  // (like value[x]) to concrete properties (like valueString) when the
  // FHIR model is loaded AND the parent type is known. In the context of
  // ViewDefinition evaluation we often evaluate against arbitrary sub-objects
  // where the type context is lost, so we do the rewrite here.
  path = path.replace(/\.ofType\(([^)]+)\)/g, (_: string, typeName: string) => {
    return typeName.charAt(0).toUpperCase() + typeName.slice(1);
  });

  return path;
}

export function processConstants(
  constants: any[] | undefined
): Record<string, any> {
  if (!constants) return {};

  const result: Record<string, any> = {};
  for (const c of constants) {
    const name = c.name;
    let value: any = undefined;

    for (const key of Object.keys(c)) {
      if (key.startsWith('value')) {
        value = c[key];
        break;
      }
    }

    if (name !== undefined) {
      result[name] = value;
    }
  }

  return result;
}

export function evaluateFhirPath(
  data: any,
  path: string,
  constants: Record<string, any> = {}
): any[] {
  const rewritten = rewritePath(path);

  return fhirpath.evaluate(
    data,
    rewritten,
    constants,
    fhirpath_r4_model,
    fhirpathOptions
  );
}
