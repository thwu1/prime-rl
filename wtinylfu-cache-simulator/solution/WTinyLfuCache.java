package wtinylfu;

import java.util.*;

public final class WTinyLfuCache {
    private final Map<Long, Node> data;
    private final FrequencySketch sketch;
    private final int maximumSize;

    private final Node headWindow;
    private final Node headProbation;
    private final Node headProtected;

    private final int maxWindow;
    private final int maxProtected;

    private int sizeWindow;
    private int sizeProtected;

    private int hitCount;
    private int missCount;
    private int evictionCount;

    public WTinyLfuCache(int maximumSize, double percentMain, double percentMainProtected) {
        this.maximumSize = maximumSize;
        int maxMain = (int) (maximumSize * percentMain);
        this.maxProtected = (int) (maxMain * percentMainProtected);
        this.maxWindow = maximumSize - maxMain;

        this.data = new HashMap<>();
        this.headWindow = new Node();
        this.headProbation = new Node();
        this.headProtected = new Node();

        this.sketch = new FrequencySketch();
        this.sketch.ensureCapacity(maximumSize);
    }

    public void access(long key) {
        Node node = data.get(key);
        if (node == null) {
            onMiss(key);
        } else if (node.status == Node.Status.WINDOW) {
            onWindowHit(node);
        } else if (node.status == Node.Status.PROBATION) {
            onProbationHit(node);
        } else if (node.status == Node.Status.PROTECTED) {
            onProtectedHit(node);
        }
    }

    private void onMiss(long key) {
        missCount++;
        sketch.increment((int) key);

        Node node = new Node(key, Node.Status.WINDOW);
        node.appendToTail(headWindow);
        data.put(key, node);
        sizeWindow++;
        evict();
    }

    private void onWindowHit(Node node) {
        hitCount++;
        sketch.increment((int) node.key);
        node.moveToTail(headWindow);
    }

    private void onProbationHit(Node node) {
        hitCount++;
        sketch.increment((int) node.key);

        node.remove();
        node.status = Node.Status.PROTECTED;
        node.appendToTail(headProtected);

        sizeProtected++;
        if (sizeProtected > maxProtected) {
            Node demote = headProtected.next;
            demote.remove();
            demote.status = Node.Status.PROBATION;
            demote.appendToTail(headProbation);
            sizeProtected--;
        }
    }

    private void onProtectedHit(Node node) {
        hitCount++;
        sketch.increment((int) node.key);
        node.moveToTail(headProtected);
    }

    private void evict() {
        if (sizeWindow <= maxWindow) {
            return;
        }

        Node candidate = headWindow.next;
        sizeWindow--;

        candidate.remove();
        candidate.status = Node.Status.PROBATION;
        candidate.appendToTail(headProbation);

        if (data.size() > maximumSize) {
            Node victim = headProbation.next;

            int candidateFreq = sketch.frequency((int) candidate.key);
            int victimFreq = sketch.frequency((int) victim.key);

            Node evict = (candidateFreq > victimFreq) ? victim : candidate;
            data.remove(evict.key);
            evict.remove();
            evictionCount++;
        }
    }

    public int getHitCount() { return hitCount; }
    public int getMissCount() { return missCount; }
    public int getEvictionCount() { return evictionCount; }
    public int getCacheSize() { return data.size(); }

    public int frequency(long key) {
        return sketch.frequency((int) key);
    }

    public List<Long> getWindowKeys() {
        return getSegmentKeys(headWindow);
    }

    public List<Long> getProbationKeys() {
        return getSegmentKeys(headProbation);
    }

    public List<Long> getProtectedKeys() {
        return getSegmentKeys(headProtected);
    }

    private List<Long> getSegmentKeys(Node head) {
        List<Long> keys = new ArrayList<>();
        Node n = head.next;
        while (n != head) {
            keys.add(n.key);
            n = n.next;
        }
        Collections.sort(keys);
        return keys;
    }
}
