#ifndef BACKOFF_H
#define BACKOFF_H


// Adaptive backoff strategy for lock-free CAS retry loops.

class adaptive_backoff
{
public:
    adaptive_backoff() {}
    void backoff() {}
    void reset() {}
};

#endif // BACKOFF_H
