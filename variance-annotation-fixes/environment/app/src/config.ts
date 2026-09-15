// Configuration types using interface declaration merging


export interface Config<out T> {
    getValue: () => T;
    getLabel: () => string;
}

export interface Config<in T> {
    getDefault: () => T;
    getDescription: () => string;
}
