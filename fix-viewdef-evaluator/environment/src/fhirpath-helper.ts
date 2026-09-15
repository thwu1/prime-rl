
const fhirpath = require('fhirpath');
let fhirpathR4Model: any = null;
try {
  fhirpathR4Model = require('fhirpath/fhir-context/r4');
} catch {
  // R4 model not available; continue without FHIR-aware type resolution
}

function rewritePath(path: string): string {
  if (path.startsWith('$this')) {
    path = 'identity()' + path.slice('$this'.length);
  }
  const ofTypeRegex = /\.ofType\(([^)]+)\)/g;
  let match: RegExpExecArray | null;
  while ((match = ofTypeRegex.exec(path)) !== null) {
    const replacement = match[1].charAt(0).toUpperCase() + match[1].slice(1);
    path = path.replace(match[0], replacement);
  }
  return path;
}

const fhirpathOptions = {
  userInvocationTable: {
    identity: { fn: (nodes: any[]) => nodes, arity: { 0: [] } },
    getResourceKey: {
      fn: (nodes: any[]) => nodes.flatMap((n: any) => [n.id]),
      arity: { 0: [] },
    },
    getReferenceKey: {
      fn: (nodes: any[], opts?: { name?: string }) => {
        const resource = opts?.name;
        return nodes.flatMap((node: any) => {
          if (!node || !node.reference) return [];
          const parts = node.reference.replaceAll('//', '').split('/_history')[0].split('/');
          const type = parts[parts.length - 2];
          const key = parts[parts.length - 1];
          if (!resource) return [key];
          return resource === type ? [key] : [];
        });
      },
      arity: { 0: [], 1: ['TypeSpecifier'] },
    },
  },
};

function processConstants(constants: any[]): Record<string, any> {
  return (constants || []).reduce((acc: Record<string, any>, x: any) => {
    let name: string = '';
    let val: any;
    for (const key in x) {
      if (key === 'name') {
        name = x[key];
      }
      if (key.startsWith('value') && typeof x[key] === 'string') {
        val = x[key];
      }
    }
    acc[name] = val;
    return acc;
  }, {});
}

export function fhirpathEvaluate(
  data: any,
  path: string,
  constants: any[] = [],
  envVars: Record<string, any> = {}
): any[] {
  const context = processConstants(constants);
  Object.assign(context, envVars);
  return fhirpath.evaluate(
    data,
    rewritePath(path),
    context,
    fhirpathR4Model,
    fhirpathOptions
  );
}

export function fhirpathValidate(path: string): boolean {
  try {
    fhirpath.compile(rewritePath(path), fhirpathR4Model, fhirpathOptions);
    return true;
  } catch {
    return false;
  }
}
