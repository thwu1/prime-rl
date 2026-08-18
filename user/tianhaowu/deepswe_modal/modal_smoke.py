import asyncio

import modal


async def main() -> None:
    app = await modal.App.lookup.aio("__pier_smoke__", create_if_missing=True)
    sandbox = await modal.Sandbox.create.aio(
        "sh",
        "-lc",
        "printf modal-sandbox-ok",
        app=app,
        image=modal.Image.debian_slim(),
        timeout=120,
    )
    stdout = await sandbox.stdout.read.aio()
    return_code = await sandbox.wait.aio()
    print(f"stdout={stdout.strip()} return_code={return_code}")


if __name__ == "__main__":
    asyncio.run(main())
