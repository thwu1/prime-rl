// Event handling types with variance constraints


export interface EventHandler<out T> {
    handle: (event: T) => void;
    readonly type: string;
}

export interface EventBus<out T> {
    dispatch: (event: T) => void;
    readonly name: string;
}

export interface EventEmitter<out T> {
    emit: (event: T) => void;
    on: (listener: (event: T) => void) => () => void;
    latest: () => T | undefined;
}
