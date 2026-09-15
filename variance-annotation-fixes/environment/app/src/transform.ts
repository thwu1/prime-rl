// Functional transformation types


export type Lens<out S, in A> = {
    get: (source: S) => A;
    set: (source: S, value: A) => S;
};

export type Reducer<in T, out A> = {
    initial: A;
    accumulate: (acc: A, item: T) => A;
};

export type Predicate<out T> = {
    test: (value: T) => boolean;
};
