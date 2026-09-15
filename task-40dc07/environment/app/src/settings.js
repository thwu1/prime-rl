const { featureToggle } = require('./utils/featureToggle');

function shouldShowFeature(isEnabled) {
  if (featureToggle('feature-pricing-v2') && isEnabled) {
    return true;
  }
  return false;
}

function shouldShowSearch() {
  if (featureToggle('feature-search-refinement')) {
    return true;
  }
  return false;
}

module.exports = { shouldShowFeature, shouldShowSearch };
