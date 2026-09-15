#!/usr/bin/env python3
"""Install MODFLOW 6 executable."""

import io
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile


def try_get_modflow():
    """Try using FloPy's get-modflow utility."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "flopy.utils.get_modflow",
             "/usr/local/bin", "--subset", "mf6"],
            input="y\n",
            capture_output=True,
            text=True,
            timeout=180,
        )
        if os.path.isfile("/usr/local/bin/mf6"):
            os.chmod("/usr/local/bin/mf6", 0o755)
            print("Installed mf6 via get-modflow")
            return True
    except Exception as e:
        print(f"get-modflow failed: {e}")
    return False


def try_nightly_build():
    """Download MODFLOW 6 from USGS nightly builds."""
    url = (
        "https://github.com/MODFLOW-USGS/modflow6-nightly-build"
        "/releases/latest/download/linux.zip"
    )
    try:
        print(f"Downloading MF6 from nightly builds...")
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "Mozilla/5.0")
        response = urllib.request.urlopen(req, timeout=180)
        z = zipfile.ZipFile(io.BytesIO(response.read()))
        z.extractall("/tmp/mf6_nightly")

        for root, dirs, files in os.walk("/tmp/mf6_nightly"):
            for f in files:
                if f == "mf6":
                    src = os.path.join(root, f)
                    dst = "/usr/local/bin/mf6"
                    shutil.copy2(src, dst)
                    os.chmod(dst, 0o755)
                    print(f"Installed mf6 from nightly build: {src}")
                    return True
    except Exception as e:
        print(f"Nightly build download failed: {e}")
    return False


def try_github_release():
    """Download MODFLOW 6 from a specific GitHub release."""
    # Try the latest stable release
    api_url = (
        "https://api.github.com/repos/MODFLOW-USGS/modflow6"
        "/releases/latest"
    )
    try:
        req = urllib.request.Request(api_url)
        req.add_header("User-Agent", "Mozilla/5.0")
        response = urllib.request.urlopen(req, timeout=60)
        import json
        release_data = json.loads(response.read())

        for asset in release_data.get("assets", []):
            name = asset["name"].lower()
            if "linux" in name and name.endswith(".zip"):
                download_url = asset["browser_download_url"]
                print(f"Downloading {download_url}...")
                req2 = urllib.request.Request(download_url)
                req2.add_header("User-Agent", "Mozilla/5.0")
                resp2 = urllib.request.urlopen(req2, timeout=180)
                z = zipfile.ZipFile(io.BytesIO(resp2.read()))
                z.extractall("/tmp/mf6_release")

                for root, dirs, files in os.walk("/tmp/mf6_release"):
                    for f in files:
                        if f == "mf6":
                            src = os.path.join(root, f)
                            dst = "/usr/local/bin/mf6"
                            shutil.copy2(src, dst)
                            os.chmod(dst, 0o755)
                            print(f"Installed mf6 from release: {src}")
                            return True
    except Exception as e:
        print(f"GitHub release download failed: {e}")
    return False


def verify_mf6():
    """Verify mf6 is installed and runs."""
    mf6_path = shutil.which("mf6")
    if mf6_path is None:
        return False
    try:
        result = subprocess.run(
            [mf6_path, "-v"],
            capture_output=True, text=True, timeout=10
        )
        print(f"mf6 version: {result.stdout.strip()}")
        return True
    except Exception:
        return False


if __name__ == "__main__":
    if verify_mf6():
        print("mf6 already available")
        sys.exit(0)

    for installer in [try_get_modflow, try_nightly_build, try_github_release]:
        if installer():
            if verify_mf6():
                sys.exit(0)

    print("ERROR: Failed to install MODFLOW 6")
    sys.exit(1)
