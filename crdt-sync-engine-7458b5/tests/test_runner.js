
const Y = require('yjs');
const { SyncEngine } = require('/app/dist/sync-engine');
const fs = require('fs');

function stateVectorsMatch(engine, peerIds) {
  const hexVectors = peerIds.map(id => {
    const sv = Y.encodeStateVector(engine.getPeer(id).doc);
    return Buffer.from(sv).toString('hex');
  });
  return hexVectors.every(v => v === hexVectors[0]);
}

function getMapJSON(engine, peerId, typeName) {
  return engine.getPeer(peerId).doc.getMap(typeName).toJSON();
}

function getTextStr(engine, peerId, typeName) {
  return engine.getPeer(peerId).doc.getText(typeName).toString();
}

function getArrayJSON(engine, peerId, typeName) {
  return engine.getPeer(peerId).doc.getArray(typeName).toJSON();
}

function deepEqual(a, b) {
  if (a === b) return true;
  if (a == null || b == null) return a === b;
  if (typeof a !== typeof b) return false;
  if (typeof a !== 'object') return a === b;
  if (Array.isArray(a) !== Array.isArray(b)) return false;
  if (Array.isArray(a)) {
    if (a.length !== b.length) return false;
    return a.every((v, i) => deepEqual(v, b[i]));
  }
  const keysA = Object.keys(a).sort();
  const keysB = Object.keys(b).sort();
  if (keysA.length !== keysB.length) return false;
  return keysA.every((k, i) => k === keysB[i] && deepEqual(a[k], b[k]));
}

const results = {};

// Test 1: Two-peer full sync convergence
function test_full_sync_convergence() {
  try {
    const engine = new SyncEngine();
    engine.addPeer('a');
    engine.addPeer('b');
    engine.localEdit('a', (doc) => {
      doc.getMap('data').set('from_a', 'alpha');
    });
    engine.localEdit('b', (doc) => {
      doc.getMap('data').set('from_b', 'beta');
    });
    engine.syncFull('a', 'b');
    const converged = stateVectorsMatch(engine, ['a', 'b']);
    const mapA = getMapJSON(engine, 'a', 'data');
    const mapB = getMapJSON(engine, 'b', 'data');
    return {
      pass: converged
        && mapA.from_a === 'alpha' && mapA.from_b === 'beta'
        && deepEqual(mapA, mapB),
      detail: { mapA, mapB, converged }
    };
  } catch (e) {
    return { pass: false, detail: e.message };
  }
}

// Test 2: Two-peer delta sync convergence
function test_delta_sync_convergence() {
  try {
    const engine = new SyncEngine();
    engine.addPeer('a');
    engine.addPeer('b');
    engine.localEdit('a', (doc) => {
      doc.getMap('data').set('x', 100);
      doc.getText('notes').insert(0, 'hello from a');
    });
    engine.localEdit('b', (doc) => {
      doc.getMap('data').set('y', 200);
      doc.getText('notes').insert(0, 'hello from b');
    });
    engine.syncDelta('a', 'b');
    const converged = stateVectorsMatch(engine, ['a', 'b']);
    const mapA = getMapJSON(engine, 'a', 'data');
    const mapB = getMapJSON(engine, 'b', 'data');
    const aHasBoth = mapA.x === 100 && mapA.y === 200;
    const bHasBoth = mapB.x === 100 && mapB.y === 200;
    return {
      pass: converged && aHasBoth && bHasBoth,
      detail: { mapA, mapB, converged }
    };
  } catch (e) {
    return { pass: false, detail: e.message };
  }
}

// Test 3: checkConvergence reports true for synced peers
function test_convergence_check_accuracy() {
  try {
    const engine = new SyncEngine();
    engine.addPeer('a');
    engine.addPeer('b');
    engine.localEdit('a', (doc) => {
      doc.getMap('data').set('k', 'v');
    });
    engine.syncFull('a', 'b');
    const manuallyConverged = stateVectorsMatch(engine, ['a', 'b']);
    const report = engine.checkConvergence();
    return {
      pass: manuallyConverged && report.converged === true,
      detail: { manuallyConverged, reportConverged: report.converged }
    };
  } catch (e) {
    return { pass: false, detail: e.message };
  }
}

// Test 4: Three-peer broadcast converges all peers
function test_three_peer_broadcast() {
  try {
    const engine = new SyncEngine();
    engine.addPeer('a');
    engine.addPeer('b');
    engine.addPeer('c');
    engine.localEdit('a', (doc) => {
      doc.getMap('data').set('from_a', 1);
    });
    engine.localEdit('b', (doc) => {
      doc.getMap('data').set('from_b', 2);
    });
    engine.localEdit('c', (doc) => {
      doc.getMap('data').set('from_c', 3);
    });
    engine.broadcastSync('full');
    const converged = stateVectorsMatch(engine, ['a', 'b', 'c']);
    const mapA = getMapJSON(engine, 'a', 'data');
    const aHasAll = mapA.from_a === 1 && mapA.from_b === 2 && mapA.from_c === 3;
    return {
      pass: converged && aHasAll,
      detail: { mapA, converged }
    };
  } catch (e) {
    return { pass: false, detail: e.message };
  }
}

// Test 5: Docless sync after full sync uses current state
function test_docless_after_full_sync() {
  try {
    const engine = new SyncEngine();
    engine.addPeer('a');
    engine.addPeer('b');
    engine.addPeer('c');
    engine.localEdit('a', (doc) => {
      doc.getMap('data').set('from_a', 'alpha');
    });
    engine.compact('a');
    engine.localEdit('b', (doc) => {
      doc.getMap('data').set('from_b', 'beta');
    });
    engine.syncFull('a', 'b');
    engine.localEdit('c', (doc) => {
      doc.getMap('data').set('from_c', 'gamma');
    });
    engine.syncDocless('a', 'c');
    const mapC = getMapJSON(engine, 'c', 'data');
    const hasAll = mapC.from_a === 'alpha'
      && mapC.from_b === 'beta'
      && mapC.from_c === 'gamma';
    return {
      pass: hasAll,
      detail: { mapC }
    };
  } catch (e) {
    return { pass: false, detail: e.message };
  }
}

// Test 6: Pending updates must not include sync-originated updates
function test_pending_updates_filtering() {
  try {
    const engine = new SyncEngine();
    engine.addPeer('a');
    engine.addPeer('b');
    engine.localEdit('a', (doc) => {
      doc.getMap('data').set('x', 1);
    });
    engine.localEdit('b', (doc) => {
      doc.getMap('data').set('y', 2);
    });
    const countBefore = engine.getPeer('a').pendingUpdates.length;
    engine.syncFull('a', 'b');
    const countAfter = engine.getPeer('a').pendingUpdates.length;
    return {
      pass: countAfter === countBefore,
      detail: { countBefore, countAfter }
    };
  } catch (e) {
    return { pass: false, detail: e.message };
  }
}

// Test 7: Complex multi-round convergence with mixed strategies
function test_complex_multi_round() {
  try {
    const engine = new SyncEngine();
    engine.addPeer('p1');
    engine.addPeer('p2');
    engine.addPeer('p3');
    engine.addPeer('p4');

    // Round 1: Text edits, full sync
    engine.localEdit('p1', (doc) => {
      doc.getText('log').insert(0, '[p1] initialized\n');
    });
    engine.localEdit('p2', (doc) => {
      doc.getText('log').insert(0, '[p2] initialized\n');
    });
    engine.broadcastSync('full');

    // Round 2: Map edits, delta sync
    engine.localEdit('p3', (doc) => {
      doc.getMap('config').set('version', 3);
      doc.getMap('config').set('debug', false);
    });
    engine.localEdit('p4', (doc) => {
      doc.getMap('config').set('env', 'production');
    });
    engine.broadcastSync('delta');

    // Round 3: Array edits, full sync
    engine.localEdit('p1', (doc) => {
      doc.getArray('events').push(['start']);
    });
    engine.localEdit('p3', (doc) => {
      doc.getArray('events').push(['checkpoint']);
    });
    engine.broadcastSync('full');

    const converged = stateVectorsMatch(engine, ['p1', 'p2', 'p3', 'p4']);
    const config = getMapJSON(engine, 'p1', 'config');
    const events = getArrayJSON(engine, 'p1', 'events');
    const hasConfig = config.version === 3 && config.debug === false && config.env === 'production';
    const hasEvents = events.length === 2;

    return {
      pass: converged && hasConfig && hasEvents,
      detail: { converged, config, events, hasConfig, hasEvents }
    };
  } catch (e) {
    return { pass: false, detail: e.message };
  }
}

// Test 8: Delta sync sends correct diffs (not empty)
function test_delta_sync_diff_correctness() {
  try {
    const engine = new SyncEngine();
    engine.addPeer('a');
    engine.addPeer('b');
    engine.localEdit('a', (doc) => {
      doc.getMap('m').set('a_key', 'a_val');
    });
    engine.localEdit('b', (doc) => {
      doc.getMap('m').set('b_key', 'b_val');
    });
    const result = engine.syncDelta('a', 'b');
    const mapA = getMapJSON(engine, 'a', 'm');
    const hasAKey = mapA.a_key === 'a_val';
    const hasBKey = mapA.b_key === 'b_val';
    const sentMeaningfulData = result.bytesSent > 10;
    return {
      pass: hasAKey && hasBKey && sentMeaningfulData,
      detail: { mapA, bytesSent: result.bytesSent }
    };
  } catch (e) {
    return { pass: false, detail: e.message };
  }
}

// Test 9: Docless sync convergence
function test_docless_sync_convergence() {
  try {
    const engine = new SyncEngine();
    engine.addPeer('a');
    engine.addPeer('b');
    engine.localEdit('a', (doc) => {
      doc.getMap('data').set('color', 'red');
      doc.getArray('items').push([10, 20, 30]);
    });
    engine.localEdit('b', (doc) => {
      doc.getMap('data').set('shape', 'circle');
      doc.getArray('items').push([40, 50]);
    });
    engine.syncDocless('a', 'b');
    const converged = stateVectorsMatch(engine, ['a', 'b']);
    const mapA = getMapJSON(engine, 'a', 'data');
    const aHasAll = mapA.color === 'red' && mapA.shape === 'circle';
    return {
      pass: converged && aHasAll,
      detail: { mapA, converged }
    };
  } catch (e) {
    return { pass: false, detail: e.message };
  }
}

// Test 10: Repeated edit-sync cycles maintain consistency
function test_repeated_edit_sync_cycles() {
  try {
    const engine = new SyncEngine();
    engine.addPeer('a');
    engine.addPeer('b');
    for (let round = 0; round < 5; round++) {
      engine.localEdit('a', (doc) => {
        doc.getMap('counters').set('a_round_' + round, round);
      });
      engine.localEdit('b', (doc) => {
        doc.getMap('counters').set('b_round_' + round, round * 10);
      });
      engine.syncFull('a', 'b');
    }
    const converged = stateVectorsMatch(engine, ['a', 'b']);
    const mapA = getMapJSON(engine, 'a', 'counters');
    let allPresent = true;
    for (let round = 0; round < 5; round++) {
      if (mapA['a_round_' + round] !== round) allPresent = false;
      if (mapA['b_round_' + round] !== round * 10) allPresent = false;
    }
    return {
      pass: converged && allPresent,
      detail: { mapA, converged }
    };
  } catch (e) {
    return { pass: false, detail: e.message };
  }
}

// Test 11: forkPeer creates a working copy with correct update tracking
function test_fork_peer_state() {
  try {
    const engine = new SyncEngine();
    engine.addPeer('origin');
    engine.localEdit('origin', (doc) => {
      doc.getMap('data').set('key', 'value');
      doc.getArray('list').push([1, 2, 3]);
    });
    engine.forkPeer('origin', 'fork');

    // Fork should have same state as origin
    const originMap = getMapJSON(engine, 'origin', 'data');
    const forkMap = getMapJSON(engine, 'fork', 'data');
    const forkArr = getArrayJSON(engine, 'fork', 'list');
    const stateMatch = deepEqual(originMap, forkMap) && deepEqual(forkArr, [1, 2, 3]);

    // Fork must track local edits via update listener
    engine.localEdit('fork', (doc) => {
      doc.getMap('data').set('fork_key', 'fork_value');
    });
    const hasPending = engine.getPeer('fork').pendingUpdates.length > 0;

    // Fork's pending buffer must NOT contain the initial state copy,
    // only the single local edit above
    const pendingCount = engine.getPeer('fork').pendingUpdates.length;

    return {
      pass: stateMatch && hasPending && pendingCount === 1,
      detail: { stateMatch, hasPending, pendingCount }
    };
  } catch (e) {
    return { pass: false, detail: e.message };
  }
}

// Test 12: forkPeer followed by independent edits and sync
function test_fork_then_sync() {
  try {
    const engine = new SyncEngine();
    engine.addPeer('a');
    engine.localEdit('a', (doc) => {
      doc.getMap('data').set('original', true);
    });
    engine.forkPeer('a', 'b');

    engine.localEdit('a', (doc) => {
      doc.getMap('data').set('from_a', 'alpha');
    });
    engine.localEdit('b', (doc) => {
      doc.getMap('data').set('from_b', 'beta');
    });

    engine.syncFull('a', 'b');

    // Use checkConvergence to verify it works with forked peers
    const report = engine.checkConvergence();
    const mapA = getMapJSON(engine, 'a', 'data');
    const hasAll = mapA.original === true && mapA.from_a === 'alpha' && mapA.from_b === 'beta';

    return {
      pass: report.converged && hasAll,
      detail: { converged: report.converged, mapA }
    };
  } catch (e) {
    return { pass: false, detail: e.message };
  }
}

// Test 13: drainPendingUpdates returns merged update and clears buffer
function test_drain_pending_updates() {
  try {
    const engine = new SyncEngine();
    engine.addPeer('a');
    engine.localEdit('a', (doc) => {
      doc.getMap('data').set('x', 1);
    });
    engine.localEdit('a', (doc) => {
      doc.getMap('data').set('y', 2);
    });

    const hasPending = engine.getPeer('a').pendingUpdates.length === 2;
    const drained = engine.drainPendingUpdates('a');
    const afterDrain = engine.getPeer('a').pendingUpdates.length;

    // Verify drained update is valid by applying to a fresh doc
    const verifyDoc = new Y.Doc();
    Y.applyUpdate(verifyDoc, drained);
    const verifyMap = verifyDoc.getMap('data').toJSON();
    const dataCorrect = verifyMap.x === 1 && verifyMap.y === 2;
    verifyDoc.destroy();

    // Second drain should return null
    const secondDrain = engine.drainPendingUpdates('a');

    return {
      pass: hasPending && afterDrain === 0 && dataCorrect && secondDrain === null,
      detail: { hasPending, afterDrain, dataCorrect, secondDrainNull: secondDrain === null }
    };
  } catch (e) {
    return { pass: false, detail: e.message };
  }
}

// Test 14: getNetworkStats returns valid values including edge cases
function test_network_stats() {
  try {
    const engine = new SyncEngine();

    // Stats before any syncs must have valid numeric values
    const statsBefore = engine.getNetworkStats();
    const validBefore = statsBefore.totalSyncs === 0
      && statsBefore.totalBytesSent === 0
      && Number.isFinite(statsBefore.avgBytesPerSync)
      && statsBefore.avgBytesPerSync >= 0;

    engine.addPeer('a');
    engine.addPeer('b');
    engine.localEdit('a', (doc) => doc.getMap('data').set('k', 'v'));
    engine.syncFull('a', 'b');

    const statsAfter = engine.getNetworkStats();
    const validAfter = statsAfter.totalSyncs === 1
      && statsAfter.totalBytesSent > 0
      && statsAfter.avgBytesPerSync === statsAfter.totalBytesSent
      && statsAfter.peerCount === 2;

    return {
      pass: validBefore && validAfter,
      detail: { statsBefore, statsAfter }
    };
  } catch (e) {
    return { pass: false, detail: e.message };
  }
}

// Test 15: Incremental sync convergence
function test_incremental_sync_convergence() {
  try {
    const engine = new SyncEngine();
    engine.addPeer('a');
    engine.addPeer('b');

    engine.localEdit('a', (doc) => {
      doc.getMap('data').set('from_a', 'alpha');
      doc.getArray('list').push([1, 2, 3]);
    });
    engine.localEdit('b', (doc) => {
      doc.getMap('data').set('from_b', 'beta');
      doc.getArray('list').push([4, 5]);
    });

    engine.syncIncremental('a', 'b');

    const converged = stateVectorsMatch(engine, ['a', 'b']);
    const mapA = getMapJSON(engine, 'a', 'data');
    const mapB = getMapJSON(engine, 'b', 'data');
    const aHasAll = mapA.from_a === 'alpha' && mapA.from_b === 'beta';
    const bHasAll = mapB.from_a === 'alpha' && mapB.from_b === 'beta';

    return {
      pass: converged && aHasAll && bHasAll,
      detail: { mapA, mapB, converged }
    };
  } catch (e) {
    return { pass: false, detail: e.message };
  }
}

// Test 16: Incremental sync buffer management
function test_incremental_sync_buffer_management() {
  try {
    const engine = new SyncEngine();
    engine.addPeer('a');
    engine.addPeer('b');

    engine.localEdit('a', (doc) => {
      doc.getMap('data').set('x', 1);
    });
    engine.localEdit('b', (doc) => {
      doc.getMap('data').set('y', 2);
    });

    const aPendingBefore = engine.getPeer('a').pendingUpdates.length;
    const bPendingBefore = engine.getPeer('b').pendingUpdates.length;

    engine.syncIncremental('a', 'b');

    const aPendingAfter = engine.getPeer('a').pendingUpdates.length;
    const bPendingAfter = engine.getPeer('b').pendingUpdates.length;

    const buffersCleared = aPendingAfter === 0 && bPendingAfter === 0;

    // Verify local edit tracking still works after incremental sync
    engine.localEdit('a', (doc) => {
      doc.getMap('data').set('z', 3);
    });
    const aNewPending = engine.getPeer('a').pendingUpdates.length;

    return {
      pass: aPendingBefore > 0 && bPendingBefore > 0 && buffersCleared && aNewPending === 1,
      detail: { aPendingBefore, bPendingBefore, aPendingAfter, bPendingAfter, aNewPending }
    };
  } catch (e) {
    return { pass: false, detail: e.message };
  }
}

// Test 17: Checkpoint diff contains only post-checkpoint changes
function test_checkpoint_diff_applied() {
  try {
    const engine = new SyncEngine();
    engine.addPeer('a');

    // Pre-checkpoint edits
    engine.localEdit('a', (doc) => {
      doc.getMap('data').set('before', 'checkpoint');
      doc.getText('notes').insert(0, 'pre-checkpoint text');
    });

    // Capture base state for verification
    const baseState = Y.encodeStateAsUpdate(engine.getPeer('a').doc);

    const cpId = engine.createCheckpoint('a');

    // Post-checkpoint edits
    engine.localEdit('a', (doc) => {
      doc.getMap('data').set('after1', 'value1');
      doc.getMap('data').set('after2', 'value2');
    });

    const diff = engine.diffSinceCheckpoint('a', cpId);
    if (!diff) return { pass: false, detail: 'diff was null but expected data' };

    // Verify diff + base produces full state
    const baseDoc = new Y.Doc();
    Y.applyUpdate(baseDoc, baseState);
    Y.applyUpdate(baseDoc, diff);
    const baseMap = baseDoc.getMap('data').toJSON();
    baseDoc.destroy();
    const hasAll = baseMap.before === 'checkpoint'
      && baseMap.after1 === 'value1' && baseMap.after2 === 'value2';

    // Verify diff alone does NOT contain pre-checkpoint data (proves differential)
    const freshDoc = new Y.Doc();
    Y.applyUpdate(freshDoc, diff);
    const freshMap = freshDoc.getMap('data').toJSON();
    freshDoc.destroy();
    const noBefore = !('before' in freshMap);

    return {
      pass: hasAll && noBefore,
      detail: { baseMap, freshMap, hasAll, noBefore }
    };
  } catch (e) {
    return { pass: false, detail: e.message };
  }
}

// Test 18: Checkpoint with no changes returns null diff
function test_checkpoint_no_changes() {
  try {
    const engine = new SyncEngine();
    engine.addPeer('a');

    engine.localEdit('a', (doc) => {
      doc.getMap('data').set('key', 'value');
    });

    const cpId = engine.createCheckpoint('a');

    // No edits after checkpoint
    const diff = engine.diffSinceCheckpoint('a', cpId);

    return {
      pass: diff === null,
      detail: { diffIsNull: diff === null }
    };
  } catch (e) {
    return { pass: false, detail: e.message };
  }
}

// Run all tests
const testFns = {
  full_sync_convergence: test_full_sync_convergence,
  delta_sync_convergence: test_delta_sync_convergence,
  convergence_check_accuracy: test_convergence_check_accuracy,
  three_peer_broadcast: test_three_peer_broadcast,
  docless_after_full_sync: test_docless_after_full_sync,
  pending_updates_filtering: test_pending_updates_filtering,
  complex_multi_round: test_complex_multi_round,
  delta_sync_diff_correctness: test_delta_sync_diff_correctness,
  docless_sync_convergence: test_docless_sync_convergence,
  repeated_edit_sync_cycles: test_repeated_edit_sync_cycles,
  fork_peer_state: test_fork_peer_state,
  fork_then_sync: test_fork_then_sync,
  drain_pending_updates: test_drain_pending_updates,
  network_stats: test_network_stats,
  incremental_sync_convergence: test_incremental_sync_convergence,
  incremental_sync_buffer_management: test_incremental_sync_buffer_management,
  checkpoint_diff_applied: test_checkpoint_diff_applied,
  checkpoint_no_changes: test_checkpoint_no_changes,
};

for (const [name, fn] of Object.entries(testFns)) {
  try {
    results[name] = fn();
  } catch (e) {
    results[name] = { pass: false, detail: 'Uncaught: ' + e.message };
  }
}

fs.writeFileSync('/tmp/test_results.json', JSON.stringify(results, null, 2));
console.log(JSON.stringify(results, null, 2));
