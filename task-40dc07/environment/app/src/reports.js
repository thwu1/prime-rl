'use strict';

const { featureToggle: isEnabled } = require('./utils/featureToggle');

function getReportConfig() {
  const config = {
    format: isEnabled('feature-pricing-v2') ? 'detailed' : 'summary',
    version: isEnabled('feature-pricing-v2') ? 2 : 1,
  };
  return config;
}

function generateReport(data) {
  const usePricingV2 = isEnabled('feature-pricing-v2');

  const processor = usePricingV2 ? processEnhanced : processLegacy;
  const header = usePricingV2 ? 'ENHANCED REPORT' : 'LEGACY REPORT';

  return header + ': ' + processor(data);
}

function processLegacy(data) {
  return 'legacy(' + data + ')';
}

function processEnhanced(data) {
  return 'enhanced(' + data + ')';
}

module.exports = { getReportConfig, generateReport };
