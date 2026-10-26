#!/usr/bin/env python3
"""
OrangeUI APK & Asset Injector (cli/inject_apks.py)
Injects APKs, 64-bit native libraries, system properties, and SELinux rules
into target system partitions, unpacked trees, or GSI images based on manifest.json.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, List, Optional

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from rich.table import Table

from cli.manifest_parser import ManifestParser
from cli.utils.deps import check_command
from cli.utils.fs import build_ext4_image, detect_filesystem, extract_ext4_image, is_sparse_image, unsparse_image
from cli.utils.logger import get_logger

logger = get_logger("INJECT_APKS")


def apply_build_prop_patch(system_root: Path, patch_file: Path) -> bool:
    """Merge custom build.prop properties into system/build.prop."""
    if not patch_file.is_file():
        return False

    candidate_props = [
        system_root / "system" / "build.prop",
        system_root / "build.prop",
    ]

    prop_path = None
    for p in candidate_props:
        if p.is_file():
            prop_path = p
            break

    if not prop_path:
        logger.warning(f"No build.prop found in {system_root}. Skipping prop patch.")
        return False

    logger.info(f"Applying build.prop patch from '{patch_file.name}' to '{prop_path}'...")
    with open(patch_file, "r", encoding="utf-8") as f:
        patch_lines = f.readlines()

    with open(prop_path, "a", encoding="utf-8") as f:
        f.write("\n# --- BEGIN ORANGEUI INJECTED PROPERTIES ---\n")
        for line in patch_lines:
            f.write(line)
        f.write("# --- END ORANGEUI INJECTED PROPERTIES ---\n")

    logger.success("build.prop successfully updated.")
    return True


def apply_sepolicy_patch(system_root: Path, sepolicy_file: Path) -> bool:
    """Append custom SELinux rules into system selinux directory."""
    if not sepolicy_file.is_file():
        return False

    candidate_sepolicy_dirs = [
        system_root / "system" / "etc" / "selinux",
        system_root / "etc" / "selinux",
    ]

    selinux_dir = None
    for d in candidate_sepolicy_dirs:
        if d.is_dir():
            selinux_dir = d
            break

    if not selinux_dir:
        logger.warning(f"No selinux directory found in {system_root}. Skipping sepolicy patch.")
        return False

    dest_rule = selinux_dir / "orangeui_sepolicy.rule"
    shutil.copy2(sepolicy_file, dest_rule)
    logger.success(f"Copied sepolicy rule to '{dest_rule}'.")
    return True


def inject_into_tree(system_root: Path, inject_dir: Path, manifest_path: Optional[Path] = None) -> int:
    """
    Inject files declared in manifest into the directory tree of the system partition.
    """
    manifest_file = manifest_path if manifest_path else (inject_dir / "manifest.json")
    manifest = ManifestParser.load(manifest_file)

    logger.banner("OrangeUI APK Injection", f"Target: {system_root} | Manifest: {manifest_file.name}")

    injected_count = 0
    table = Table(title="Injection Summary", border_style="cyan")
    table.add_column("Type", justify="center")
    table.add_column("Source", style="yellow")
    table.add_column("Destination In System", style="green")

    for entry in manifest.entries:
        if not entry.exists:
            logger.fail(f"Required inject file '{entry.source_rel}' does not exist on disk!")

        # Calculate target destination on host
        # The target_abs starts with /system or /
        rel_target = entry.target_abs.lstrip("/")
        # If target starts with system/ but system_root itself contains system/
        if rel_target.startswith("system/") and (system_root / "system").is_dir():
            dest_file = system_root / rel_target
        elif (system_root / "system").is_dir() and not rel_target.startswith("system/"):
            dest_file = system_root / "system" / rel_target
        else:
            # Flat partition where root is system
            clean_rel = rel_target[7:] if rel_target.startswith("system/") else rel_target
            dest_file = system_root / clean_rel

        dest_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(entry.source_path, dest_file)
        
        # Set standard permissions: 0644 for files, 0755 for dirs
        try:
            os.chmod(dest_file, 0o644)
            os.chmod(dest_file.parent, 0o755)
        except Exception:
            pass

        injected_count += 1
        type_str = "APK" if entry.is_apk else ("LIB64" if entry.is_so else "FILE")
        table.add_row(type_str, entry.source_rel, str(dest_file.relative_to(system_root)))

    from rich.console import Console
    Console().print(table)

    # Check for build.prop.patch
    prop_patch = inject_dir / "build.prop.patch"
    if prop_patch.is_file():
        apply_build_prop_patch(system_root, prop_patch)

    # Check for sepolicy.rule
    sepolicy_patch = inject_dir / "sepolicy.rule"
    if sepolicy_patch.is_file():
        apply_sepolicy_patch(system_root, sepolicy_patch)

    logger.success(f"Injected {injected_count} item(s) into system.")
    return injected_count


def inject_into_image(image_path: Path, output_image: Path, inject_dir: Path, manifest_path: Optional[Path] = None) -> Path:
    """
    Inject files into an EXT4 system.img by extracting, modifying, and rebuilding.
    """
    if not image_path.is_file():
        logger.fail(f"Image not found: {image_path}")

    fs_type = detect_filesystem(image_path)
    if fs_type != "ext4":
        logger.fail(f"Direct image injection currently requires EXT4 filesystem (found: {fs_type}).")

    raw_img = image_path
    temp_raw = None
    if is_sparse_image(image_path):
        temp_raw = image_path.with_name(image_path.stem + "_raw.img")
        raw_img = unsparse_image(image_path, temp_raw)

    orig_size = raw_img.stat().st_size
    # Expand slightly to fit newly injected apps
    target_size = int(orig_size * 1.15) + (32 * 1024 * 1024)
    # Align to 4096
    target_size = ((target_size + 4095) // 4096) * 4096

    with tempfile.TemporaryDirectory(prefix="orangeui_img_inject_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        extracted_root = tmp_path / "system_root"
        extracted_root.mkdir()

        # Extract image
        if not extract_ext4_image(raw_img, extracted_root):
            logger.fail("Failed to extract filesystem image for injection.")

        # Inject
        inject_into_tree(extracted_root, inject_dir, manifest_path)

        # Repack ext4
        output_image.parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"Rebuilding EXT4 image '{output_image.name}' (size: {target_size / (1024*1024):.2f} MB)...")
        if not build_ext4_image(extracted_root, output_image, target_size, mount_point="/system"):
            logger.fail("Failed to rebuild EXT4 image.")

    if temp_raw and temp_raw.exists():
        temp_raw.unlink()

    logger.success(f"Successfully generated injected system image: '{output_image}'")
    return output_image


def generate_ota_update_zip(inject_dir: Path, output_zip: Path, version: str = "1.0") -> Path:
    """
    Generate an OTA-compatible flashable ZIP (OrangeUI_Update_vX.X.zip)
    containing injected APKs and an updater script.
    """
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    manifest_file = inject_dir / "manifest.json"
    manifest = ManifestParser.load(manifest_file)

    logger.info(f"Creating OTA update archive '{output_zip.name}'...")
    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # Include manifest
        zf.write(manifest_file, "manifest.json")

        # Include injected files
        for entry in manifest.entries:
            if entry.exists:
                zf.write(entry.source_path, entry.source_rel)

        # Include build.prop.patch and sepolicy if present
        for extra in ["build.prop.patch", "sepolicy.rule"]:
            efile = inject_dir / extra
            if efile.is_file():
                zf.write(efile, extra)

        # Create basic updater script
        updater_script = [
            f"# OrangeUI OTA Update Script v{version}",
            "ui_print(\"Installing OrangeUI Liquid Glass System Apps...\");",
        ]
        for entry in manifest.entries:
            updater_script.append(f'package_extract_file("{entry.source_rel}", "{entry.target_abs}");')
            updater_script.append(f'set_metadata("{entry.target_abs}", "uid", 0, "gid", 0, "mode", 0644);')
        updater_script.append("ui_print(\"OrangeUI update complete!\");")

        zf.writestr("META-INF/com/google/android/updater-script", "\n".join(updater_script))
        zf.writestr("META-INF/com/google/android/update-binary", "#!/sbin/sh\nexit 0\n")

    logger.success(f"OTA update package created: '{output_zip}'")
    return output_zip


def main():
    parser = argparse.ArgumentParser(
        description="OrangeUI APK & Asset Injector",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--target", "-t", type=str, required=True, help="Target system directory or system.img")
    parser.add_argument("--output", "-o", type=str, help="Output image file (if target is system.img)")
    parser.add_argument("--inject", "-i", type=str, default="inject", help="Path to inject directory (default: inject/)")
    parser.add_argument("--manifest", "-m", type=str, help="Custom manifest.json path")
    parser.add_argument("--ota-zip", type=str, help="Generate an OTA flashable ZIP package at specified path")

    args = parser.parse_args()

    inject_dir = Path(args.inject)
    manifest_p = Path(args.manifest) if args.manifest else None

    if args.ota_zip:
        generate_ota_update_zip(inject_dir, Path(args.ota_zip))
        sys.exit(0)

    target_path = Path(args.target)
    if target_path.is_file():
        out_img = Path(args.output) if args.output else target_path.with_name(target_path.stem + "_injected.img")
        inject_into_image(target_path, out_img, inject_dir, manifest_p)
    elif target_path.is_dir():
        inject_into_tree(target_path, inject_dir, manifest_p)
    else:
        logger.fail(f"Target path does not exist: {target_path}")


if __name__ == "__main__":
    main()
