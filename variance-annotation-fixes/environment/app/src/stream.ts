// Stream processing types with circular type references


export type Stream<T> = {
    head: T;
    transform: StreamTransform<T>;
};

export type StreamTransform<T> = (pipe: StreamPipeline<T>) => void;

export type StreamPipeline<T> = {
    source: Stream<T>;
    buffer: T[];
};
