/**
 * createTransformer - Compose multiple jscodeshift transform functions into a single transform.
 *
 * Each transform function receives (j, root) where:
 *   j    - the jscodeshift API object
 *   root - the root Collection of the parsed source
 *
 * Transforms are applied in order on the same AST, then the final source is emitted.
 */
function createTransformer(transforms) {
  return function (fileInfo, api, options) {
    const j = api.jscodeshift;
    const root = j(fileInfo.source);

    transforms.forEach(function (transform) {
      transform(j, root);
    });

    return root.toSource(
      (options && options.printOptions) || { quote: 'single' }
    );
  };
}

module.exports = { createTransformer };
