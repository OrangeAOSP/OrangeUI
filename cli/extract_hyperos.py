#!/usr/bin/env python3
"""
OrangeUI HyperOS Extraction Tool (cli/extract_hyperos.py)
Extracts system applications and 64-bit native libraries from HyperOS donor images,
analyzes MIUI/HyperOS dependencies, and generates injection manifests.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from rich.table import Table

from cli.manifest_parser import ManifestParser
from cli.utils.deps import check_command
from cli.utils.fs import detect_filesystem, extract_erofs_image, extract_ext4_image, is_sparse_image, unsparse_image
from cli.utils.logger import get_logger

logger = get_logger("EXTRACT_HYPEROS")

KNOWN_HYPEROS_TARGETS = {
    "MiuiHome": "MiuiHome.apk",
    "Launcher3": "Launcher3.apk",
    "MiuiSystemUI": "MiuiSystemUI.apk",
    "SystemUI": "SystemUI.apk",
    "Settings": "Settings.apk",
    "MiuiGallery": "MiuiGallery.apk",
    "MIUIGalleryGlobal": "MIUIGalleryGlobal.apk",
    "MiuiCamera": "MiuiCamera.apk",
    "ThemeManager": "ThemeManager.apk",
    "SecurityAdd": "SecurityAdd.apk",
    "SecurityCenter": "SecurityCenter.apk",
    "MIUISecurityCenterGlobal": "MIUISecurityCenterGlobal.apk",
    "MIUIAod": "MIUIAod.apk",
}


def scan_dex_strings(apk_path: Path) -> Tuple[Set[str], Set[str]]:
    """
    Extract string literals and class references from all classes*.dex inside an APK
    without external decompiler dependencies.
    """
    miui_refs = set()
    loaded_libs = set()

    if not apk_path.is_file() or not zipfile.is_zipfile(apk_path):
        return miui_refs, loaded_libs

    try:
        with zipfile.ZipFile(apk_path, "r") as zf:
            for item in zf.namelist():
                if item.startswith("classes") and item.endswith(".dex"):
                    dex_data = zf.read(item)
                    # Search for ASCII strings matching MIUI/HyperOS packages
                    # Regex for Lcom/miui/... or com/miui/...
                    for match in re.finditer(b"(?:L)?com/miui/[a-zA-Z0-9_/]+", dex_data):
                        clean = match.group(0).decode("ascii", errors="ignore").replace("/", ".").lstrip("L")
                        miui_refs.add(clean)

                    for match in re.finditer(b"(?:L)?miui/[a-zA-Z0-9_/]+", dex_data):
                        clean = match.group(0).decode("ascii", errors="ignore").replace("/", ".").lstrip("L")
                        miui_refs.add(clean)

                    # Look for System.loadLibrary calls or .so names
                    for match in re.finditer(b"lib[a-zA-Z0-9_\\-\\.]+\\.so", dex_data):
                        loaded_libs.add(match.group(0).decode("ascii", errors="ignore"))

                elif item.startswith("lib/arm64-v8a/") and item.endswith(".so"):
                    loaded_libs.add(Path(item).name)

    except Exception as e:
        logger.warning(f"Error scanning DEX bytecode of {apk_path.name}: {e}")

    return miui_refs, loaded_libs


def scan_elf_dependencies(so_path: Path) -> List[str]:
    """Inspect ELF NEEDED shared library dependencies via readelf."""
    readelf_bin = check_command("readelf")
    if not readelf_bin or not so_path.is_file():
        return []

    try:
        res = subprocess.run([readelf_bin, "-d", str(so_path)], capture_output=True, text=True)
        if res.returncode == 0:
            return re.findall(r"\(NEEDED\)\s+Shared library:\s+\[(.*?)\]", res.stdout)
    except Exception:
        pass
    return []


def locate_apps_in_tree(system_root: Path) -> List[Path]:
    """Find all APK files anywhere in system or subpartitions tree."""
    found_apks = []
    seen_names = set()
    for f in system_root.rglob("*.apk"):
        if f.is_file():
            found_apks.append(f)
    return sorted(found_apks, key=lambda p: p.name)


def extract_single_partition_image(img_path: Path, dest_dir: Path) -> bool:
    """Unpack a single partition image (EXT4/EROFS) into destination folder."""
    fs_type = detect_filesystem(img_path)
    logger.info(f"Unpacking partition '{img_path.name}' ({fs_type.upper()}) to '{dest_dir.name}'...")
    dest_dir.mkdir(parents=True, exist_ok=True)

    img_to_unpack = img_path
    temp_raw = None
    if is_sparse_image(img_path):
        temp_raw = dest_dir.parent / f"_{img_path.stem}_raw.img"
        img_to_unpack = unsparse_image(img_path, temp_raw)

    success = False
    if fs_type == "ext4":
        success = extract_ext4_image(img_to_unpack, dest_dir)
    elif fs_type == "erofs":
        success = extract_erofs_image(img_to_unpack, dest_dir)
    else:
        logger.warning(f"Skipping unsupported image format for {img_path.name}: {fs_type}")

    if temp_raw and temp_raw.exists():
        temp_raw.unlink()

    return success


def extract_hyperos_apps(
    source: Path,
    output_dir: Path,
    targets: Optional[List[str]] = None,
    extract_all: bool = False,
    include_libs: bool = True
) -> Dict[str, Path]:
    """
    Extract HyperOS applications and libraries from donor image or directory.
    """
    if not source.exists():
        logger.fail(f"Source path does not exist: {source}")

    output_dir.mkdir(parents=True, exist_ok=True)
    temp_mount_dir = None

    logger.banner("OrangeUI HyperOS Extractor", f"Source: {source} -> Output: {output_dir}")

    # Determine if source is a single image or directory of images/files
    if source.is_file():
        temp_mount_dir = output_dir / "_donor_root"
        if temp_mount_dir.exists():
            shutil.rmtree(temp_mount_dir)
        temp_mount_dir.mkdir(parents=True, exist_ok=True)

        if not extract_single_partition_image(source, temp_mount_dir):
            logger.fail(f"Failed to extract donor image '{source.name}'.")

        root_search_dir = temp_mount_dir
    else:
        # Check if directory contains .img partition files (e.g. from repack_super unpack)
        img_files = [f for f in source.glob("*.img") if f.stat().st_size > 0]
        # Prefer system, product, system_ext, mi_ext
        priority_keywords = ["system", "product", "system_ext", "mi_ext"]
        relevant_imgs = [f for f in img_files if any(k in f.stem.lower() for k in priority_keywords)]
        if not relevant_imgs:
            relevant_imgs = img_files

        if relevant_imgs:
            logger.info(f"Discovered {len(relevant_imgs)} partition image(s) in {source.name}. Unpacking...")
            temp_mount_dir = output_dir / "_donor_root"
            if temp_mount_dir.exists():
                shutil.rmtree(temp_mount_dir)
            temp_mount_dir.mkdir(parents=True, exist_ok=True)

            for pimg in relevant_imgs:
                part_dest = temp_mount_dir / pimg.stem
                extract_single_partition_image(pimg, part_dest)

            root_search_dir = temp_mount_dir
        else:
            root_search_dir = source

    all_apks = locate_apps_in_tree(root_search_dir)
    logger.info(f"Discovered {len(all_apks)} APK file(s) in donor system.")

    if not all_apks:
        logger.fail(f"No APK files found under {root_search_dir}")

    # Determine filter
    selected_apks: List[Path] = []
    if extract_all:
        selected_apks = all_apks
    elif targets:
        target_lower = [t.lower() for t in targets]
        for apk in all_apks:
            if any(t in apk.name.lower() or t in apk.parent.name.lower() for t in target_lower):
                selected_apks.append(apk)
    else:
        # Default: extract known HyperOS apps
        for apk in all_apks:
            for k in KNOWN_HYPEROS_TARGETS:
                if k.lower() in apk.name.lower() or k.lower() in apk.parent.name.lower():
                    selected_apks.append(apk)
                    break

    logger.info(f"Selected {len(selected_apks)} APK(s) matching criteria.")

    # Locate all lib64 directories recursively
    existing_lib64 = []
    for d in root_search_dir.rglob("lib64"):
        if d.is_dir() and d not in existing_lib64:
            existing_lib64.append(d)

    extracted_records: Dict[str, Path] = {}
    manifest_map: Dict[str, str] = {}
    needed_so_files: Set[str] = set()

    analysis_table = Table(title="Extracted HyperOS Apps & Dependencies", border_style="cyan")
    analysis_table.add_column("App Name", style="bold white")
    analysis_table.add_column("MIUI Class Refs", justify="right", style="yellow")
    analysis_table.add_column("Native (.so) Libs", style="magenta")
    analysis_table.add_column("Output File", style="green")

    out_lib64_dir = output_dir / "lib64"
    if include_libs:
        out_lib64_dir.mkdir(parents=True, exist_ok=True)

    for apk in selected_apks:
        dest_apk = output_dir / apk.name
        shutil.copy2(apk, dest_apk)
        extracted_records[apk.name] = dest_apk

        # Inspect dependencies
        miui_refs, loaded_libs = scan_dex_strings(dest_apk)
        needed_so_files.update(loaded_libs)

        # Target injection path calculation
        # If was in priv-app: /system/priv-app/<Folder>/<Name>.apk
        # If in app: /system/app/<Folder>/<Name>.apk
        parent_name = apk.parent.name
        if "priv-app" in str(apk):
            rom_target = f"/system/priv-app/{parent_name}/{apk.name}"
        else:
            rom_target = f"/system/app/{parent_name}/{apk.name}"

        manifest_map[apk.name] = rom_target

        analysis_table.add_row(
            apk.stem,
            str(len(miui_refs)),
            f"{len(loaded_libs)} lib(s)",
            apk.name
        )

    from rich.console import Console
    Console().print(analysis_table)

    # Collect .so files if requested
    collected_libs = 0
    if include_libs and existing_lib64 and needed_so_files:
        for lib_name in needed_so_files:
            for d in existing_lib64:
                cand = d / lib_name
                if cand.is_file():
                    dest_lib = out_lib64_dir / lib_name
                    shutil.copy2(cand, dest_lib)
                    manifest_map[f"lib64/{lib_name}"] = f"/system/lib64/{lib_name}"
                    collected_libs += 1
                    break

        logger.info(f"Copied {collected_libs} matching 64-bit native library/libraries into '{out_lib64_dir.name}'.")

    # Generate manifest.json in output_dir
    manifest_dest = output_dir / "manifest.json"
    import json
    with open(manifest_dest, "w", encoding="utf-8") as f:
        json.dump(manifest_map, f, indent=2)

    logger.success(f"Generated extraction manifest '{manifest_dest.name}' with {len(manifest_map)} entries.")

    # Cleanup temp directory if any
    if temp_mount_dir and temp_mount_dir.exists():
        shutil.rmtree(temp_mount_dir, ignore_errors=True)

    return extracted_records


def main():
    parser = argparse.ArgumentParser(
        description="OrangeUI HyperOS System App Extractor & Dependency Analyzer",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--system", "-s", type=str, required=True, help="Path to donor system.img or extracted system folder")
    parser.add_argument("--output", "-o", type=str, default="inject", help="Output directory (default: inject/)")
    parser.add_argument("--targets", "-t", nargs="+", help="Specific app names to extract (e.g. MiuiHome Settings)")
    parser.add_argument("--all", "-a", action="store_true", help="Extract all discovered APKs")
    parser.add_argument("--no-libs", action="store_true", help="Do not search and copy .so shared libraries")

    args = parser.parse_args()

    extract_hyperos_apps(
        source=Path(args.system),
        output_dir=Path(args.output),
        targets=args.targets,
        extract_all=args.all,
        include_libs=not args.no_libs
    )


if __name__ == "__main__":
    main()
