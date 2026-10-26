#!/usr/bin/env python3
"""
OrangeUI GSI Builder (cli/build_gsi.py)
Automates downloading LineageOS / AOSP Treble GSI (.img.xz), decompressing,
injecting OrangeUI APKs & libraries, and optionally applying MTK / Charoite payload fixes.
"""

import argparse
import lzma
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Optional

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from rich.progress import BarColumn, DownloadColumn, Progress, TextColumn, TimeRemainingColumn, TransferSpeedColumn

from cli.inject_apks import inject_into_image
from cli.utils.deps import check_command
from cli.utils.logger import get_logger

logger = get_logger("BUILD_GSI")

CHAROITE_PAYLOAD_DIR = Path("/mnt/loopfox/phones/charoite/Fabric/payload")


def download_file_with_progress(url: str, dest_path: Path) -> Path:
    """Download a remote file with a rich progress bar and resume/check support."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    if dest_path.is_file() and dest_path.stat().st_size > 0:
        logger.info(f"Target file already exists: {dest_path} ({dest_path.stat().st_size / (1024*1024):.1f} MB). Skipping download.")
        return dest_path

    logger.info(f"Downloading from '{url}' to '{dest_path}'...")
    
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (OrangeUI-GSI-Downloader/1.0)"}
    )

    try:
        with urllib.request.urlopen(req) as response:
            total_size = int(response.headers.get("content-length", 0))

            with Progress(
                TextColumn("[bold blue]{task.fields[filename]}", justify="right"),
                BarColumn(),
                "[progress.percentage]{task.percentage:>3.1f}%",
                "•",
                DownloadColumn(),
                "•",
                TransferSpeedColumn(),
                "•",
                TimeRemainingColumn(),
            ) as progress:
                task = progress.add_task("download", filename=dest_path.name, total=total_size)
                
                with open(dest_path, "wb") as out_f:
                    buffer_size = 64 * 1024
                    while True:
                        chunk = response.read(buffer_size)
                        if not chunk:
                            break
                        out_f.write(chunk)
                        progress.update(task, advance=len(chunk))

    except Exception as e:
        if dest_path.exists():
            dest_path.unlink()
        logger.fail(f"Failed to download GSI archive from {url}: {e}")

    logger.success(f"Download complete: '{dest_path.name}'.")
    return dest_path


def decompress_xz(xz_path: Path, output_img: Optional[Path] = None) -> Path:
    """Decompress a .xz archive into raw .img."""
    if not xz_path.is_file():
        logger.fail(f"XZ archive not found: {xz_path}")

    target_img = output_img if output_img else xz_path.with_suffix("")
    if target_img.suffix != ".img":
        target_img = target_img.with_suffix(".img")

    if target_img.is_file() and target_img.stat().st_size > 0:
        logger.info(f"Decompressed image already exists: '{target_img.name}'. Skipping extraction.")
        return target_img

    logger.info(f"Decompressing '{xz_path.name}' -> '{target_img.name}'...")

    xz_bin = check_command("xz")
    if xz_bin:
        # Use native xz multi-threaded decompression
        cmd = [xz_bin, "-d", "-k", "-c", str(xz_path)]
        try:
            with open(target_img, "wb") as out_f:
                res = subprocess.run(cmd, stdout=out_f, stderr=subprocess.PIPE)
                if res.returncode == 0:
                    logger.success(f"Decompressed raw image successfully via xz ({target_img.stat().st_size / (1024*1024):.1f} MB).")
                    return target_img
        except Exception as e:
            logger.warning(f"Native xz decompression failed: {e}. Falling back to Python lzma...")

    # Fallback to Python lzma stream
    try:
        with lzma.open(xz_path, "rb") as in_f, open(target_img, "wb") as out_f:
            shutil.copyfileobj(in_f, out_f, length=1024 * 1024)
        logger.success(f"Decompressed raw image successfully via Python lzma ({target_img.stat().st_size / (1024*1024):.1f} MB).")
    except Exception as e:
        if target_img.exists():
            target_img.unlink()
        logger.fail(f"Failed to decompress XZ archive: {e}")

    return target_img


def apply_charoite_fixes_to_inject(inject_dir: Path, payload_dir: Optional[Path] = None) -> Path:
    """
    Copy MediaTek fixes (Lights HAL, PHH script, overlays, NDK libs)
    from charoite payload into inject/ directory and update manifest.json.
    """
    src_payload = payload_dir if payload_dir else CHAROITE_PAYLOAD_DIR
    if not src_payload.is_dir():
        logger.fail(f"Charoite payload directory not found: {src_payload}")

    logger.banner("Applying Xiaomi Charoite (MT6789) Fixes", f"Payload: {src_payload}")

    # Copy binary lights HAL and scripts
    bin_dir = src_payload / "bin"
    if bin_dir.is_dir():
        dest_bin = inject_dir / "bin"
        dest_bin.mkdir(parents=True, exist_ok=True)
        for f in bin_dir.glob("*"):
            shutil.copy2(f, dest_bin / f.name)
            logger.info(f"Copied MTK executable: {f.name}")

    # Copy init rc files
    etc_init = src_payload / "etc" / "init"
    if etc_init.is_dir():
        dest_etc = inject_dir / "etc" / "init"
        dest_etc.mkdir(parents=True, exist_ok=True)
        for f in etc_init.glob("*.rc"):
            shutil.copy2(f, dest_etc / f.name)
            logger.info(f"Copied init script: {f.name}")

    # Copy NDK 64-bit libraries
    lib64_dir = src_payload / "lib64"
    if lib64_dir.is_dir():
        dest_lib64 = inject_dir / "lib64"
        dest_lib64.mkdir(parents=True, exist_ok=True)
        for f in lib64_dir.glob("*.so"):
            shutil.copy2(f, dest_lib64 / f.name)
            logger.info(f"Copied MTK NDK library: {f.name}")

    # Copy treble overlays
    overlay_dir = src_payload / "product" / "overlay"
    if overlay_dir.is_dir():
        dest_overlay = inject_dir / "product" / "overlay"
        dest_overlay.mkdir(parents=True, exist_ok=True)
        for f in overlay_dir.glob("*.apk"):
            shutil.copy2(f, dest_overlay / f.name)
            logger.info(f"Copied Charoite Treble overlay: {f.name}")

    # Update build.prop.patch with PHH backlight fix
    prop_patch = inject_dir / "build.prop.patch"
    charoite_props = [
        "\n# --- Xiaomi Charoite (Redmi Note 15 Pro 4G MT6789) Fixes ---\n",
        "persist.sys.phh.backlight.scale=0\n",
        "ro.vendor.mediatek.platform=MT6789\n",
        "persist.sys.qcom-brightness=-1\n"
    ]
    with open(prop_patch, "a", encoding="utf-8") as f:
        f.writelines(charoite_props)

    logger.success("Charoite payload and property patches merged into inject/ directory.")
    return inject_dir


def build_gsi_image(
    gsi_source: str,
    inject_dir: Path,
    output_image: Path,
    is_charoite: bool = False,
    charoite_payload: Optional[Path] = None
) -> Path:
    """
    Main GSI build pipeline:
    1. Resolve local file or download URL.
    2. Decompress .xz.
    3. Apply MTK Charoite fixes if requested.
    4. Inject OrangeUI APKs & assets.
    5. Save final modified GSI image.
    """
    logger.banner("OrangeUI GSI Builder Pipeline", f"Device Mode: {'Redmi Note 15 Pro 4G (Charoite)' if is_charoite else 'Universal Treble'}")

    # Step 1: Download or locate source
    if gsi_source.startswith("http://") or gsi_source.startswith("https://"):
        download_cache = REPO_ROOT / "releases" / "cache"
        filename = gsi_source.split("?")[0].split("/")[-1]
        download_path = download_cache / filename
        xz_file = download_file_with_progress(gsi_source, download_path)
    else:
        xz_file = Path(gsi_source)
        if not xz_file.exists():
            logger.fail(f"GSI source path not found: {gsi_source}")

    # Step 2: Decompress if needed
    if xz_file.suffix == ".xz":
        raw_gsi = decompress_xz(xz_file)
    else:
        raw_gsi = xz_file

    # Step 3: Apply Charoite fixes to inject/ if requested
    if is_charoite:
        apply_charoite_fixes_to_inject(inject_dir, charoite_payload)

    # Step 4: Inject OrangeUI into GSI
    output_image.parent.mkdir(parents=True, exist_ok=True)
    injected_img = inject_into_image(
        image_path=raw_gsi,
        output_image=output_image,
        inject_dir=inject_dir
    )

    logger.success(f"OrangeUI GSI build complete: '{injected_img}'")
    return injected_img


def main():
    parser = argparse.ArgumentParser(
        description="OrangeUI GSI Automated Builder",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--url", "-u", type=str, help="Download URL of Treble GSI (.img.xz)")
    parser.add_argument("--image", "-i", type=str, help="Path to local GSI image or .xz file")
    parser.add_argument("--inject", type=str, default="inject", help="Path to inject directory (default: inject/)")
    parser.add_argument("--output", "-o", type=str, default="releases/OrangeUI-GSI.img", help="Path to output GSI image")
    parser.add_argument("--charoite", action="store_true", help="Apply Xiaomi Charoite (MT6789) fixes")
    parser.add_argument("--charoite-payload", type=str, help="Custom path to Fabric/payload directory")

    args = parser.parse_args()

    gsi_src = args.url or args.image
    if not gsi_src:
        logger.fail("Either --url or --image must be specified.")

    payload_path = Path(args.charoite_payload) if args.charoite_payload else None

    build_gsi_image(
        gsi_source=gsi_src,
        inject_dir=Path(args.inject),
        output_image=Path(args.output),
        is_charoite=args.charoite,
        charoite_payload=payload_path
    )


if __name__ == "__main__":
    main()
