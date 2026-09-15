
// UMD global access test - script file (no imports or exports).
// Requires 'export as namespace sigil' in the declaration file.

const umdSignal = sigil<number>('umd-test');
umdSignal.set(99);
const umdName: string = umdSignal.name;
const umdVal: number | undefined = umdSignal.get();
const umdPeeked: number | undefined = umdSignal.peek();
umdSignal.update((c: number | undefined) => (c ?? 0) + 1);
