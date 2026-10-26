#!/usr/bin/env python3
"""
OrangeUI Xiaomi Charoite Builder (cli/charoite_builder.py)
Dedicated pipeline for Redmi Note 15 Pro 4G (MT6789):
- Injects MediaTek HALs, lights service, NDK libraries, and treble overlays from Fabric/payload.
- Packages OrangeUI Liquid Glass interface.
- Builds A/B dynamic super.img or GSI system.img.
- Produces fastboot flashable ZIP archive: releases/charoite/OrangeUI-charoite-v1.0.zip.
"""

import argparse
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Optional

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cli.build_gsi import build_gsi_image, decompress_xz, download_file_with_progress
from cli.inject_apks import inject_into_image
from cli.repack_super import repack_super
from cli.utils.deps import check_command
from cli.utils.logger import get_logger

logger = get_logger("CHAROITE_BUILDER")

DEFAULT_PAYLOAD = Path("/mnt/loopfox/phones/charoite/Fabric/payload")
DEFAULT_GSI_URL = "https://github.com/Doze-off/lineage_treble/releases/download/v2026.06.03/LineageOS-23.2_GSI_treble_arm64-ab-VANILLA-20260603.img.xz"


def create_charoite_fastboot_package(
    system_img: Path,
    output_zip: Path,
    boot_img: Optional[Path] = None,
    super_img: Optional[Path] = None,
    version: str = "1.0"
) -> Path:
    """Package images with Windows and Linux fastboot flashing scripts."""
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    logger.info(f"Generating flashable fastboot package: '{output_zip}'...")

    # Fastboot flash script for Linux (flash.sh)
    flash_sh = [
        "#!/bin/bash",
        "set -e",
        'echo "=== Flashing OrangeUI for Redmi Note 15 Pro 4G (Charoite) ==="',
        "fastboot devices",
    ]

    # Fastboot flash script for Windows (flash.bat)
    flash_bat = [
        "@echo off",
        "echo === Flashing OrangeUI for Redmi Note 15 Pro 4G (Charoite) ===",
        "fastboot devices",
    ]

    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        if super_img and super_img.is_file():
            zf.write(super_img, "super.img")
            flash_sh.append("fastboot flash super super.img")
            flash_bat.append("fastboot flash super super.img")
        elif system_img and system_img.is_file():
            zf.write(system_img, "system.img")
            flash_sh.append("fastboot flash system system.img")
            flash_bat.append("fastboot flash system system.img")

        if boot_img and boot_img.is_file():
            zf.write(boot_img, "boot.img")
            flash_sh.append("fastboot flash boot boot.img")
            flash_bat.append("fastboot flash boot boot.img")

        flash_sh.extend([
            "fastboot -w || true",
            'echo "Flashing complete! Rebooting..."',
            "fastboot reboot"
        ])

        flash_bat.extend([
            "fastboot -w",
            "echo Flashing complete! Rebooting...",
            "fastboot reboot",
            "pause"
        ])

        zf.writestr("flash.sh", "\n".join(flash_sh) + "\n")
        zf.writestr("flash.bat", "\r\n".join(flash_bat) + "\r\n")

    logger.success(f"Fastboot flashable package built: '{output_zip}'")
    return output_zip


def build_charoite(
    gsi_source: Optional[str] = None,
    payload_dir: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    version: str = "1.0"
) -> Path:
    """Full Charoite automated build pipeline."""
    logger.banner("Xiaomi Charoite Builder (Redmi Note 15 Pro 4G)", "Target Platform: MediaTek MT6789 (Helio G99)")

    payload = payload_dir if payload_dir else DEFAULT_PAYLOAD
    out_dir = output_dir if output_dir else REPO_ROOT / "releases" / "charoite"
    out_dir.mkdir(parents=True, exist_ok=True)

    gsi_url_or_path = gsi_source if gsi_source else DEFAULT_GSI_URL
    inject_dir = REPO_ROOT / "inject"

    # Step 1: Build GSI with Charoite MTK payload
    system_img = out_dir / "system.img"
    build_gsi_image(
        gsi_source=gsi_url_or_path,
        inject_dir=inject_dir,
        output_image=system_img,
        is_charoite=True,
        charoite_payload=payload
    )

    # Step 2: Check for boot.img in charoite phone directory if present
    boot_img_candidate = Path("/mnt/loopfox/phones/charoite/boot.img")
    boot_img = boot_img_candidate if boot_img_candidate.is_file() else None

    # Step 3: Package into flashable ZIP
    zip_path = out_dir / f"OrangeUI-charoite-v{version}.zip"
    create_charoite_fastboot_package(
        system_img=system_img,
        output_zip=zip_path,
        boot_img=boot_img,
        version=version
    )

    logger.success(f"Charoite release pipeline successfully completed: '{zip_path}'")
    return zip_path


def main():
    parser = argparse.ArgumentParser(
        description="OrangeUI Charoite (Redmi Note 15 Pro 4G MT6789) Release Builder",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--gsi", "-g", type=str, default=DEFAULT_GSI_URL, help="GSI source URL or local path")
    parser.add_argument("--payload", "-p", type=str, default=str(DEFAULT_PAYLOAD), help="Path to Fabric/payload directory")
    parser.add_argument("--output", "-o", type=str, default="releases/charoite", help="Release directory")
    parser.add_argument("--version", "-v", type=str, default="1.0", help="Release version tag")

    args = parser.parse_args()

    build_charoite(
        gsi_source=args.gsi,
        payload_dir=Path(args.payload),
        output_dir=Path(args.output),
        version=args.version
    )


if __name__ == "__main__":
    main()
