'use strict';

/**
 * Telemetry data formatters for human-readable output.
 */

function formatBytes(bytes) {
  var units = ['B', 'KB', 'MB', 'GB', 'TB'];
  var unitIndex = 0;
  var value = bytes;

  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex++;
  }

  return value.toFixed(2) + ' ' + units[unitIndex];
}

function formatDuration(ms) {
  if (ms < 1000) return ms + 'ms';
  if (ms < 60000) return (ms / 1000).toFixed(1) + 's';
  if (ms < 3600000) return (ms / 60000).toFixed(1) + 'min';
  return (ms / 3600000).toFixed(1) + 'h';
}

function formatTimestamp(ts) {
  return new Date(ts).toISOString();
}

function formatMetric(name, value, unit) {
  return name + ': ' + value + (unit ? ' ' + unit : '');
}

module.exports = { formatBytes, formatDuration, formatTimestamp, formatMetric };
