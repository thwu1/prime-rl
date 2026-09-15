const { featureToggle } = require('./utils/featureToggle');

function getDashboardLayout() {
  if (!featureToggle('feature-pricing-v2')) {
    return 'legacy-grid';
  } else {
    return 'new-flex';
  }
}

module.exports = { getDashboardLayout };
