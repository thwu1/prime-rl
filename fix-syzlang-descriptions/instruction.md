The syzkaller fuzzing pipeline for the `/dev/vdma` virtual DMA controller driver is broken. The pipeline consists of:

- UAPI kernel header (ground truth, do not modify): `/app/include/vdma.h`
- Syzlang description file: `/app/sys/vdma.txt`
- Validation tool: `/app/tools/syzlang_lint.py`
- Syzlang syntax reference: `/app/docs/syzlang_syntax.md`

The descriptions in `/app/sys/vdma.txt` must correctly and completely model the kernel interface defined in `/app/include/vdma.h`, following standard syzkaller syzlang conventions. The linter at `/app/tools/syzlang_lint.py` must accurately validate any syzlang description file against any UAPI header.

Both the description file and the validation tool are suspected to have issues. The UAPI header and the syzlang syntax reference are the authoritative sources of truth — do not blindly trust the linter's output.

When everything is correct, running `python3 /app/tools/syzlang_lint.py /app/include/vdma.h /app/sys/vdma.txt` should report zero errors.