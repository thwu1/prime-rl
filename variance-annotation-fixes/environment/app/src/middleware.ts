// Request handling middleware types


export type Handler<out Req, in out Res> = {
    handle: (request: Req) => Res;
};

export type Interceptor<out T> = {
    before: (value: T) => T;
    after: (value: T) => T;
};
