const { featureToggle: ft } = require('./utils/featureToggle');

function getApiVersion() {
  return ft('feature-pricing-v2') ? 'v2' : 'v1';
}

module.exports = { getApiVersion };
