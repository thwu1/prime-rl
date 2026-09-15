#!/usr/bin/env python3
"""Fix all variance annotation and configuration bugs in the reactive library.

Writes complete corrected file contents — does not read or patch existing files.
"""

import os
import json


def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(content)


def fix_all():
    # Fix tsconfig.json — remove strictFunctionTypes: false
    write_file('/app/tsconfig.json', json.dumps({
        "compilerOptions": {
            "target": "ES2020",
            "module": "commonjs",
            "strict": True,
            "declaration": True,
            "outDir": "./dist",
            "rootDir": "./src",
            "esModuleInterop": True,
            "skipLibCheck": True,
            "forceConsistentCasingInFileNames": True
        },
        "include": ["src/**/*"]
    }, indent=2) + '\n')

    # Fix types.ts
    write_file('/app/src/types.ts', '''\
// Core reactive types for the state management library


export type Provider<out T> = {
    get: () => T;
    map: <U>(fn: (value: T) => U) => Provider<U>;
};

export type Consumer<in T> = {
    accept: (value: T) => void;
    contramap: <U>(fn: (value: U) => T) => Consumer<U>;
};

export type Mapper<in T, out U> = {
    apply: (input: T) => U;
};

export type Store<in out T> = {
    get: () => T;
    set: (value: T) => void;
    subscribe: (listener: (value: T) => void) => () => void;
};

export type ReadonlyStore<out T> = {
    get: () => T;
    subscribe: (listener: (value: T) => void) => () => void;
};
''')

    # Fix events.ts
    write_file('/app/src/events.ts', '''\
// Event handling types with variance constraints


export interface EventHandler<in T> {
    handle: (event: T) => void;
    readonly type: string;
}

export interface EventBus<in T> {
    dispatch: (event: T) => void;
    readonly name: string;
}

export interface EventEmitter<in out T> {
    emit: (event: T) => void;
    on: (listener: (event: T) => void) => () => void;
    latest: () => T | undefined;
}
''')

    # Fix stream.ts — circular references require explicit annotations
    write_file('/app/src/stream.ts', '''\
// Stream processing types with circular type references


export type Stream<in out T> = {
    head: T;
    transform: StreamTransform<T>;
};

export type StreamTransform<in out T> = (pipe: StreamPipeline<T>) => void;

export type StreamPipeline<in out T> = {
    source: Stream<T>;
    buffer: T[];
};
''')

    # Fix config.ts — merged declarations must have consistent annotations
    write_file('/app/src/config.ts', '''\
// Configuration types using interface declaration merging


export interface Config<out T> {
    getValue: () => T;
    getLabel: () => string;
}

export interface Config<out T> {
    getDefault: () => T;
    getDescription: () => string;
}
''')

    # Fix transform.ts
    write_file('/app/src/transform.ts', '''\
// Functional transformation types


export type Lens<in out S, in out A> = {
    get: (source: S) => A;
    set: (source: S, value: A) => S;
};

export type Reducer<in T, in out A> = {
    initial: A;
    accumulate: (acc: A, item: T) => A;
};

export type Predicate<in T> = {
    test: (value: T) => boolean;
};
''')

    # Fix codec.ts
    write_file('/app/src/codec.ts', '''\
// Data encoding and decoding types


export type Encoder<in T> = {
    encode: (value: T) => string;
};

export type Decoder<out T> = {
    decode: (raw: string) => T;
};

export type Codec<in out T> = {
    encode: (value: T) => string;
    decode: (raw: string) => T;
};
''')

    # Fix middleware.ts
    write_file('/app/src/middleware.ts', '''\
// Request handling middleware types


export type Handler<in Req, out Res> = {
    handle: (request: Req) => Res;
};

export type Interceptor<in out T> = {
    before: (value: T) => T;
    after: (value: T) => T;
};
''')

    # Implement compose.ts with all 8 types
    write_file('/app/src/compose.ts', '''\
// Type-safe transformation pipeline types


export type Source<out T> = {
    pull: () => T;
    pipe: <U>(through: Through<T, U>) => Source<U>;
};

export type Sink<in T> = {
    push: (value: T) => void;
    compose: <U>(through: Through<U, T>) => Sink<U>;
};

export type Through<in T, out U> = {
    transform: (input: T) => U;
    andThen: <V>(next: Through<U, V>) => Through<T, V>;
};

export type Pipeline<in T, out U> = {
    feed: (input: T) => U;
    append: <V>(stage: Through<U, V>) => Pipeline<T, V>;
};

export type Duplex<out T, in U> = {
    read: () => T;
    write: (value: U) => void;
    adapt: <V, W>(readMap: (t: T) => V, writeMap: (w: W) => U) => Duplex<V, W>;
};

export type Channel<in out T> = {
    send: (value: T) => void;
    receive: () => T;
    bimap: (fn: (value: T) => T) => Channel<T>;
};

export type Fold<in T, in out R> = {
    step: (state: R, item: T) => R;
    extract: () => R;
};

export type Splitter<in T, out A, out B> = {
    split: (value: T) => { left: A; right: B };
    classify: (value: T) => boolean;
};
''')

    # Fix index.ts — re-export all modules
    write_file('/app/src/index.ts', '''\

export * from './types';
export * from './events';
export * from './stream';
export * from './config';
export * from './transform';
export * from './codec';
export * from './middleware';
export * from './compose';
''')

    print("All variance annotation fixes applied.")


if __name__ == '__main__':
    fix_all()
