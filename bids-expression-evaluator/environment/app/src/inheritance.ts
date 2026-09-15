
export interface ParsedName {
  entities: Record<string, string>;
  suffix: string;
  extension: string;
}

export interface SidecarFile {
  name: string;
  metadata: Record<string, unknown>;
}

export interface DatasetNode {
  name: string;
  files?: SidecarFile[];
  directories?: DatasetNode[];
}

export interface InheritanceResult {
  file_id: string;
  resolved_metadata: Record<string, unknown>;
  applied_sidecars: string[];
}

/**
 * Parse a BIDS-style filename into entities, suffix, and extension.
 *
 * Filenames follow the pattern:
 *   key1-val1_key2-val2_..._suffix.extension
 *
 * Compound extensions like .nii.gz must be handled as a single unit.
 */
export function parseFilename(name: string): ParsedName {
  const dotIdx = name.lastIndexOf('.');
  let extension = '';
  let stem = name;
  if (dotIdx !== -1) {
    extension = name.slice(dotIdx);
    stem = name.slice(0, dotIdx);
  }

  const parts = stem.split('_');
  const entities: Record<string, string> = {};
  let suffix = '';

  for (const part of parts) {
    const hyphenIdx = part.indexOf('-');
    if (hyphenIdx !== -1) {
      const key = part.slice(0, hyphenIdx);
      const value = part.slice(hyphenIdx + 1);
      entities[key] = value;
    } else {
      suffix = part;
    }
  }

  return { entities, suffix, extension };
}

/**
 * Check if a sidecar file name matches a target file for inheritance purposes.
 *
 * A sidecar matches the target when:
 * 1. The sidecar has a .json extension
 * 2. The sidecar's suffix matches the target's suffix
 * 3. Every entity in the SIDECAR's name exists in the target with the same value
 *    (the sidecar may have fewer entities — it applies broadly)
 */
function matchesSidecar(sidecarName: string, target: ParsedName): boolean {
  const sidecar = parseFilename(sidecarName);
  if (sidecar.extension !== '.json') return false;
  if (sidecar.suffix !== target.suffix) return false;

  for (const [key, value] of Object.entries(target.entities)) {
    if (sidecar.entities[key] !== undefined && sidecar.entities[key] !== value) {
      return false;
    }
    if (sidecar.entities[key] === undefined) return false;
  }
  return true;
}

/**
 * Walk the dataset tree to find the chain of directory nodes
 * from the root to the specified directory path.
 */
function findPathNodes(tree: DatasetNode, dirParts: string[]): DatasetNode[] {
  const result: DatasetNode[] = [tree];
  let current = tree;

  for (const part of dirParts) {
    if (!current.directories) return result;
    const next = current.directories.find(d => d.name === part);
    if (!next) return result;
    result.push(next);
    current = next;
  }

  return result;
}

/**
 * Resolve the effective sidecar metadata for a file in the dataset tree.
 *
 * Implements the BIDS Inheritance Principle:
 * - Walk from the dataset root to the file's directory
 * - At each level, find JSON sidecars that match the target file
 * - Merge metadata so that closer (deeper) sidecars override more distant ones
 */
export function resolveInheritance(
  tree: DatasetNode,
  filePath: string
): InheritanceResult {
  const pathParts = filePath.split('/').filter(p => p.length > 0);
  const fileName = pathParts[pathParts.length - 1];
  const dirParts = pathParts.slice(0, -1);
  const target = parseFilename(fileName);

  const pathNodes = findPathNodes(tree, dirParts);
  if (pathNodes.length === 0) {
    return { file_id: filePath, resolved_metadata: {}, applied_sidecars: [] };
  }

  // Only examines the immediate (deepest) directory for sidecars.
  const lastNode = pathNodes[pathNodes.length - 1];
  const resolved: Record<string, unknown> = {};
  const applied: string[] = [];

  if (lastNode.files) {
    for (const file of lastNode.files) {
      if (matchesSidecar(file.name, target)) {
        Object.assign(resolved, file.metadata);
        const nodePath = dirParts.length > 0 ? '/' + dirParts.join('/') : '';
        applied.push(nodePath + '/' + file.name);
      }
    }
  }

  return {
    file_id: filePath,
    resolved_metadata: resolved,
    applied_sidecars: applied,
  };
}

/**
 * Resolve inheritance for multiple files in a dataset.
 */
export function resolveAll(
  tree: DatasetNode,
  filePaths: string[]
): InheritanceResult[] {
  return filePaths.map(fp => resolveInheritance(tree, fp));
}
