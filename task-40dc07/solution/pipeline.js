
'use strict';

const { createTransformer } = require('/app/codemods/createTransformer');

var TOGGLE_NAME = 'feature-pricing-v2';

/**
 * Determine the local binding name for featureToggle in this file.
 * Handles: const { featureToggle } = require(...)
 *          const { featureToggle: alias } = require(...)
 */
function getToggleLocalName(j, root) {
  var localName = 'featureToggle';

  root.find(j.VariableDeclarator).forEach(function (path) {
    var init = path.node.init;
    if (
      init &&
      init.type === 'CallExpression' &&
      init.callee &&
      init.callee.name === 'require' &&
      init.arguments.length > 0 &&
      typeof init.arguments[0].value === 'string' &&
      init.arguments[0].value.indexOf('featureToggle') !== -1
    ) {
      var id = path.node.id;
      if (id.type === 'ObjectPattern') {
        id.properties.forEach(function (prop) {
          if (
            prop.type === 'Property' &&
            prop.key &&
            prop.key.name === 'featureToggle'
          ) {
            localName = prop.value.name;
          }
        });
      }
    }
  });

  return localName;
}

function isTargetToggleCall(node, localName) {
  return (
    node &&
    node.type === 'CallExpression' &&
    node.callee &&
    node.callee.type === 'Identifier' &&
    node.callee.name === localName &&
    node.arguments.length === 1 &&
    node.arguments[0] &&
    node.arguments[0].value === TOGGLE_NAME
  );
}

function isNegatedTargetToggle(node, localName) {
  return (
    node &&
    node.type === 'UnaryExpression' &&
    node.operator === '!' &&
    isTargetToggleCall(node.argument, localName)
  );
}

// -----------------------------------------------------------------------
// Transform 1: Inline variable assignments of the toggle call
// Handles:  const x = featureToggle('feature-pricing-v2');
//           const x = !featureToggle('feature-pricing-v2');
// Replaces all usages of x with the original expression, then removes
// the variable declaration.
// -----------------------------------------------------------------------
function inlineToggleVariable(j, root) {
  var localName = getToggleLocalName(j, root);

  // We must collect before mutating
  var toProcess = [];

  root.find(j.VariableDeclarator).forEach(function (path) {
    var init = path.node.init;
    if (!init) return;
    if (
      isTargetToggleCall(init, localName) ||
      isNegatedTargetToggle(init, localName)
    ) {
      toProcess.push(path);
    }
  });

  toProcess.forEach(function (path) {
    var init = path.node.init;
    var varName = path.node.id.name;

    // Find all references to this variable (excluding the declaration itself)
    root.find(j.Identifier, { name: varName }).forEach(function (refPath) {
      // Skip the declarator's own id
      if (refPath.parent.node === path.node && refPath.node === path.node.id) {
        return;
      }
      // Clone the init expression to avoid sharing AST nodes
      var replacement = JSON.parse(JSON.stringify(init));
      j(refPath).replaceWith(replacement);
    });

    // Remove the variable declaration
    var declPath = path.parent;
    if (
      declPath.node.type === 'VariableDeclaration' &&
      declPath.node.declarations.length === 1
    ) {
      j(declPath).remove();
    } else {
      j(path).remove();
    }
  });
}

// -----------------------------------------------------------------------
// Transform 2: Remove toggle from ternary expressions
// featureToggle('...') ? A : B  -->  A
// !featureToggle('...') ? A : B  -->  B
// -----------------------------------------------------------------------
function removeToggleTernary(j, root) {
  var localName = getToggleLocalName(j, root);

  root.find(j.ConditionalExpression).forEach(function (path) {
    var test = path.node.test;
    if (isTargetToggleCall(test, localName)) {
      j(path).replaceWith(path.node.consequent);
    } else if (isNegatedTargetToggle(test, localName)) {
      j(path).replaceWith(path.node.alternate);
    }
  });
}

// -----------------------------------------------------------------------
// Transform 3: Remove toggle from if-else statements
// if (featureToggle('...')) { A } else { B }  -->  A (unwrapped)
// if (!featureToggle('...')) { A } else { B }  -->  B (unwrapped)
// -----------------------------------------------------------------------
function removeToggleIfElse(j, root) {
  var localName = getToggleLocalName(j, root);

  root.find(j.IfStatement).forEach(function (path) {
    var test = path.node.test;
    var keepBlock = null;

    if (isTargetToggleCall(test, localName)) {
      keepBlock = path.node.consequent;
    } else if (isNegatedTargetToggle(test, localName)) {
      keepBlock = path.node.alternate;
    }

    if (keepBlock) {
      if (keepBlock.type === 'BlockStatement') {
        // Replace the if-statement with the block's individual statements
        path.replace.apply(path, keepBlock.body);
      } else {
        path.replace(keepBlock);
      }
    }
  });
}

// -----------------------------------------------------------------------
// Transform 4: Simplify logical AND expressions with the toggle
// featureToggle('...') && expr  -->  expr
// expr && featureToggle('...')  -->  expr
// -----------------------------------------------------------------------
function removeToggleLogicalAnd(j, root) {
  var localName = getToggleLocalName(j, root);

  root.find(j.LogicalExpression, { operator: '&&' }).forEach(function (path) {
    if (isTargetToggleCall(path.node.left, localName)) {
      j(path).replaceWith(path.node.right);
    } else if (isTargetToggleCall(path.node.right, localName)) {
      j(path).replaceWith(path.node.left);
    }
  });
}

// -----------------------------------------------------------------------
// Transform 5: Remove unused function declarations
// After toggle removal, some functions may no longer be called.
// -----------------------------------------------------------------------
function removeUnusedFunctions(j, root) {
  // Collect all identifiers that appear in non-declaration positions
  var referenced = {};

  root.find(j.Identifier).forEach(function (idPath) {
    var parent = idPath.parent.node;
    // Skip if this identifier IS the name in a function declaration
    if (parent.type === 'FunctionDeclaration' && parent.id === idPath.node) {
      return;
    }
    referenced[idPath.node.name] = true;
  });

  root.find(j.FunctionDeclaration).forEach(function (path) {
    var funcName = path.node.id.name;
    if (!referenced[funcName]) {
      j(path).remove();
    }
  });
}

// -----------------------------------------------------------------------
// Transform 6: Remove unused require imports
// If no destructured binding from a require() call is still used,
// remove the entire declaration.
// -----------------------------------------------------------------------
function removeUnusedImports(j, root) {
  root.find(j.VariableDeclaration).forEach(function (declPath) {
    var declarations = declPath.node.declarations;

    declarations.forEach(function (declarator) {
      var init = declarator.init;
      if (
        !init ||
        init.type !== 'CallExpression' ||
        !init.callee ||
        init.callee.name !== 'require'
      ) {
        return;
      }

      var id = declarator.id;
      if (id.type !== 'ObjectPattern') return;

      // Check if ALL destructured bindings are unused
      var allUnused = id.properties.every(function (prop) {
        var boundName = prop.value.name;
        var usageCount = 0;

        root.find(j.Identifier, { name: boundName }).forEach(function (refPath) {
          // Skip references inside the import declaration itself
          if (refPath.parent.node === prop) return;
          if (refPath.node === prop.key) return;
          if (refPath.node === prop.value) return;
          usageCount++;
        });

        return usageCount === 0;
      });

      if (allUnused) {
        if (declarations.length === 1) {
          j(declPath).remove();
        }
      }
    });
  });
}

// -----------------------------------------------------------------------
// Compose all transforms in dependency order
// -----------------------------------------------------------------------
var transform = createTransformer([
  inlineToggleVariable,   // must run first: inline variable assignments
  removeToggleTernary,    // then remove from ternaries
  removeToggleIfElse,     // then remove from if-else blocks
  removeToggleLogicalAnd, // then simplify logical AND
  removeUnusedFunctions,  // cleanup: remove dead functions
  removeUnusedImports,    // cleanup: remove dead imports
]);

module.exports = transform;
module.exports.default = transform;
module.exports.parser = 'babel';
