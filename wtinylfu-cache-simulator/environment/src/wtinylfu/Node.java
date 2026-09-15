package wtinylfu;

public final class Node {
    public enum Status { WINDOW, PROBATION, PROTECTED }

    public final long key;
    public Node prev;
    public Node next;
    public Status status;

    /** Creates a new sentinel node. */
    public Node() {
        this.key = Long.MIN_VALUE;
        this.prev = this;
        this.next = this;
    }

    /** Creates a new, unlinked node. */
    public Node(long key, Status status) {
        this.status = status;
        this.key = key;
    }

    public void moveToTail(Node head) {
        remove();
        appendToTail(head);
    }

    /** Appends the node to the tail of the list. */
    public void appendToTail(Node head) {
        Node tail = head.prev;
        head.prev = this;
        tail.next = this;
        next = head;
        prev = tail;
    }

    /** Removes the node from the list. */
    public void remove() {
        prev.next = next;
        next.prev = prev;
        next = prev = null;
    }
}
