import * as Y from 'yjs';


export interface PeerState {
  id: string;
  doc: Y.Doc;
  pendingUpdates: Uint8Array[];
  compactedSnapshot: Uint8Array | null;
  syncCount: number;
}

export interface SyncResult {
  bytesSent: number;
  strategy: string;
}

export interface ConvergenceReport {
  converged: boolean;
  states: Record<string, any>;
  peerCount: number;
}

export interface NetworkStats {
  totalSyncs: number;
  totalBytesSent: number;
  avgBytesPerSync: number;
  peerCount: number;
}

export interface Checkpoint {
  id: string;
  peerId: string;
  stateData: Uint8Array;
  timestamp: number;
}

export class SyncEngine {
  private peers: Map<string, PeerState> = new Map();
  private totalBytesSent: number = 0;
  private totalSyncs: number = 0;
  private checkpoints: Map<string, Checkpoint> = new Map();
  private checkpointCounter: number = 0;

  addPeer(id: string): void {
    const doc = new Y.Doc();
    const peer: PeerState = {
      id,
      doc,
      pendingUpdates: [],
      compactedSnapshot: null,
      syncCount: 0,
    };

    doc.on('update', (update: Uint8Array, origin: any) => {
      if (origin !== 'sync') {
        peer.pendingUpdates.push(update);
      }
    });

    this.peers.set(id, peer);
  }

  forkPeer(existingId: string, newId: string): void {
    const existing = this.getPeerOrThrow(existingId);
    const doc = new Y.Doc();
    const peer: PeerState = {
      id: newId,
      doc,
      pendingUpdates: [],
      compactedSnapshot: null,
      syncCount: 0,
    };

    doc.on('update', (update: Uint8Array, origin: any) => {
      if (origin !== 'sync') {
        peer.pendingUpdates.push(update);
      }
    });

    const state = Y.encodeStateAsUpdate(existing.doc);
    Y.applyUpdate(doc, state, 'sync');
    this.peers.set(newId, peer);
  }

  localEdit(peerId: string, fn: (doc: Y.Doc) => void): void {
    const peer = this.getPeerOrThrow(peerId);
    peer.doc.transact(() => fn(peer.doc), 'local');
  }

  syncFull(id1: string, id2: string): SyncResult {
    const p1 = this.getPeerOrThrow(id1);
    const p2 = this.getPeerOrThrow(id2);
    const s1 = Y.encodeStateAsUpdate(p1.doc);
    const s2 = Y.encodeStateAsUpdate(p2.doc);
    Y.applyUpdate(p1.doc, s2, 'sync');
    Y.applyUpdate(p2.doc, s1, 'sync');
    p1.compactedSnapshot = null;
    p2.compactedSnapshot = null;
    const bytes = s1.byteLength + s2.byteLength;
    this.totalBytesSent += bytes;
    this.totalSyncs++;
    p1.syncCount++;
    p2.syncCount++;
    return { bytesSent: bytes, strategy: 'full' };
  }

  syncDelta(id1: string, id2: string): SyncResult {
    const p1 = this.getPeerOrThrow(id1);
    const p2 = this.getPeerOrThrow(id2);
    const sv1 = Y.encodeStateVector(p1.doc);
    const sv2 = Y.encodeStateVector(p2.doc);
    const diff1 = Y.encodeStateAsUpdate(p1.doc, sv2);
    const diff2 = Y.encodeStateAsUpdate(p2.doc, sv1);
    Y.applyUpdate(p1.doc, diff2, 'sync');
    Y.applyUpdate(p2.doc, diff1, 'sync');
    p1.compactedSnapshot = null;
    p2.compactedSnapshot = null;
    const bytes = diff1.byteLength + diff2.byteLength;
    this.totalBytesSent += bytes;
    this.totalSyncs++;
    p1.syncCount++;
    p2.syncCount++;
    return { bytesSent: bytes, strategy: 'delta' };
  }

  syncDocless(id1: string, id2: string): SyncResult {
    const p1 = this.getPeerOrThrow(id1);
    const p2 = this.getPeerOrThrow(id2);
    this.compact(id1);
    this.compact(id2);
    const s1 = p1.compactedSnapshot!;
    const s2 = p2.compactedSnapshot!;
    const sv1 = Y.encodeStateVectorFromUpdate(s1);
    const sv2 = Y.encodeStateVectorFromUpdate(s2);
    const diff1 = Y.diffUpdate(s1, sv2);
    const diff2 = Y.diffUpdate(s2, sv1);
    p1.compactedSnapshot = Y.mergeUpdates([s1, diff2]);
    p2.compactedSnapshot = Y.mergeUpdates([s2, diff1]);
    Y.applyUpdate(p1.doc, diff2, 'sync');
    Y.applyUpdate(p2.doc, diff1, 'sync');
    const bytes = diff1.byteLength + diff2.byteLength;
    this.totalBytesSent += bytes;
    this.totalSyncs++;
    p1.syncCount++;
    p2.syncCount++;
    return { bytesSent: bytes, strategy: 'docless' };
  }

  syncIncremental(id1: string, id2: string): SyncResult {
    const p1 = this.getPeerOrThrow(id1);
    const p2 = this.getPeerOrThrow(id2);
    let bytes = 0;

    if (p1.pendingUpdates.length > 0) {
      const merged1 = Y.mergeUpdates(p1.pendingUpdates);
      Y.applyUpdate(p2.doc, merged1, 'sync');
      bytes += merged1.byteLength;
    }
    if (p2.pendingUpdates.length > 0) {
      const merged2 = Y.mergeUpdates(p2.pendingUpdates);
      Y.applyUpdate(p1.doc, merged2, 'sync');
      bytes += merged2.byteLength;
    }

    p1.pendingUpdates = [];
    p2.pendingUpdates = [];
    p1.compactedSnapshot = null;
    p2.compactedSnapshot = null;

    this.totalBytesSent += bytes;
    this.totalSyncs++;
    p1.syncCount++;
    p2.syncCount++;
    return { bytesSent: bytes, strategy: 'incremental' };
  }

  compact(peerId: string): void {
    const peer = this.getPeerOrThrow(peerId);
    peer.compactedSnapshot = Y.encodeStateAsUpdate(peer.doc);
    peer.pendingUpdates = [];
  }

  checkConvergence(): ConvergenceReport {
    const ids = Array.from(this.peers.keys());
    const states: Record<string, any> = {};
    for (const id of ids) {
      states[id] = this.peers.get(id)!.doc.toJSON();
    }

    const vectors = ids.map(id =>
      Y.encodeStateVector(this.peers.get(id)!.doc)
    );

    for (let i = 1; i < vectors.length; i++) {
      if (vectors[0].byteLength !== vectors[i].byteLength) {
        return { converged: false, states, peerCount: ids.length };
      }
      for (let b = 0; b < vectors[0].byteLength; b++) {
        if (vectors[0][b] !== vectors[i][b]) {
          return { converged: false, states, peerCount: ids.length };
        }
      }
    }
    return { converged: true, states, peerCount: ids.length };
  }

  broadcastSync(strategy: 'full' | 'delta' | 'docless' = 'full'): void {
    const ids = Array.from(this.peers.keys());
    for (let i = 0; i < ids.length; i++) {
      for (let j = i + 1; j < ids.length; j++) {
        const syncFn =
          strategy === 'full'
            ? this.syncFull.bind(this)
            : strategy === 'delta'
              ? this.syncDelta.bind(this)
              : this.syncDocless.bind(this);
        syncFn(ids[i], ids[j]);
      }
    }
  }

  createCheckpoint(peerId: string): string {
    const peer = this.getPeerOrThrow(peerId);
    const id = `cp_${this.checkpointCounter++}`;
    this.checkpoints.set(id, {
      id,
      peerId,
      stateData: Y.encodeStateVector(peer.doc),
      timestamp: Date.now(),
    });
    return id;
  }

  diffSinceCheckpoint(peerId: string, checkpointId: string): Uint8Array | null {
    const peer = this.getPeerOrThrow(peerId);
    const checkpoint = this.checkpoints.get(checkpointId);
    if (!checkpoint) throw new Error(`Unknown checkpoint: ${checkpointId}`);
    if (checkpoint.peerId !== peerId) throw new Error('Checkpoint belongs to different peer');
    const diff = Y.encodeStateAsUpdate(peer.doc, checkpoint.stateData);
    if (diff.byteLength <= 2) return null;
    return diff;
  }

  drainPendingUpdates(peerId: string): Uint8Array | null {
    const peer = this.getPeerOrThrow(peerId);
    if (peer.pendingUpdates.length === 0) return null;
    const merged = Y.mergeUpdates(peer.pendingUpdates);
    peer.pendingUpdates = [];
    return merged;
  }

  getNetworkStats(): NetworkStats {
    return {
      totalSyncs: this.totalSyncs,
      totalBytesSent: this.totalBytesSent,
      avgBytesPerSync: this.totalSyncs > 0 ? this.totalBytesSent / this.totalSyncs : 0,
      peerCount: this.peers.size,
    };
  }

  getPeer(peerId: string): PeerState | undefined {
    return this.peers.get(peerId);
  }

  getAllPeerIds(): string[] {
    return Array.from(this.peers.keys());
  }

  private getPeerOrThrow(id: string): PeerState {
    const peer = this.peers.get(id);
    if (!peer) throw new Error(`Unknown peer: ${id}`);
    return peer;
  }
}
