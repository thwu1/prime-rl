#include <windows.h>

int main(void) {
    HANDLE h = GetStdHandle(STD_OUTPUT_HANDLE);
    DWORD n;
    WriteFile(h, "hello\n", 6, &n, NULL);
    char buf[MAX_PATH];
    GetModuleFileNameA(NULL, buf, MAX_PATH);
    GetCurrentDirectoryA(MAX_PATH, buf);
    HANDLE heap = GetProcessHeap();
    void *p = HeapAlloc(heap, 0, 64);
    HeapFree(heap, 0, p);
    SetLastError(0);
    GetLastError();
    ExitProcess(0);
    return 0;
}
