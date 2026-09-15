// Core reactive types for the state management library


export type Provider<in T> = {
    get: () => T;
    map: <U>(fn: (value: T) => U) => Provider<U>;
};

export type Consumer<out T> = {
    accept: (value: T) => void;
    contramap: <U>(fn: (value: U) => T) => Consumer<U>;
};

export type Mapper<out T, in U> = {
    apply: (input: T) => U;
};

export type Store<out T> = {
    get: () => T;
    set: (value: T) => void;
    subscribe: (listener: (value: T) => void) => () => void;
};

export type ReadonlyStore<out T> = {
    get: () => T;
    subscribe: (listener: (value: T) => void) => () => void;
};
