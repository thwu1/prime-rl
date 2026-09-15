const { featureToggle } = require('./utils/featureToggle');

function legacyFormat(message) {
  return '[LEGACY] ' + message;
}

function modernFormat(message) {
  return '[MODERN] ' + message;
}

function formatNotification(message) {
  const useLegacy = !featureToggle('feature-pricing-v2');

  if (useLegacy) {
    return legacyFormat(message);
  } else {
    return modernFormat(message);
  }
}

module.exports = { formatNotification };
