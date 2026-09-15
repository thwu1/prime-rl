// Data encoding and decoding types


export type Encoder<out T> = {
    encode: (value: T) => string;
};

export type Decoder<in out T> = {
    decode: (raw: string) => T;
};

export type Codec<out T> = {
    encode: (value: T) => string;
    decode: (raw: string) => T;
};
