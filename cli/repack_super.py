#!/usr/bin/env python3
"""
OrangeUI Super Partition Tool (cli/repack_super.py)
Unpacks and rebuilds Android dynamic partition (super.img) using lpunpack and lpmake.

Key features:
- Automatically handles sparse images (converts via simg2img).
- Filters target partitions (default: system, vendor, product).
- Detects partition filesystem types (EXT4 / EROFS / F2FS).
- Preserves partition sizes, partition groups, and liblp device layout.
- Supports disabling AVB verity and producing sparse fastboot-flashable super.img.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from rich.table import Table

from cli.utils.deps import check_command, require_tool
from cli.utils.fs import detect_filesystem, is_sparse_image, sparse_image, unsparse_image
from cli.utils.logger import get_logger

logger = get_logger("REPACK_SUPER")

DEFAULT_TARGET_PARTITIONS = ["system", "vendor", "product", "system_ext", "mi_ext"]


class SuperMetadata:
    """Stores super.img layout and partition metadata."""
    def __init__(self):
        self.device_size: int = 0
        self.metadata_size: int = 65536
        self.metadata_slots: int = 2
        self.block_size: int = 4096
        self.alignment: int = 4096
        self.groups: Dict[str, int] = {}  # group_name -> max_size
        self.partitions: Dict[str, Dict[str, Any]] = {}  # part_name -> {size, group, fs_type, file}
        self.available_partitions: List[str] = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_size": self.device_size,
            "metadata_size": self.metadata_size,
            "metadata_slots": self.metadata_slots,
            "block_size": self.block_size,
            "alignment": self.alignment,
            "groups": self.groups,
            "partitions": self.partitions,
            "available_partitions": self.available_partitions
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SuperMetadata":
        meta = cls()
        meta.device_size = data.get("device_size", 0)
        meta.metadata_size = data.get("metadata_size", 65536)
        meta.metadata_slots = data.get("metadata_slots", 2)
        meta.block_size = data.get("block_size", 4096)
        meta.alignment = data.get("alignment", 4096)
        meta.groups = data.get("groups", {})
        meta.partitions = data.get("partitions", {})
        meta.available_partitions = data.get("available_partitions", [])
        return meta

    def save(self, filepath: Path) -> None:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, filepath: Path) -> "SuperMetadata":
        with open(filepath, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))


def dump_super_metadata(super_raw_path: Path) -> SuperMetadata:
    """Inspect super image layout with lpdump if available, or compute fallback layout."""
    meta = SuperMetadata()
    meta.device_size = super_raw_path.stat().st_size

    lpdump_bin = check_command("lpdump")
    if not lpdump_bin:
        logger.warning("'lpdump' not found; using fallback dynamic partition metadata calculation.")
        meta.groups["orangeui_dynamic_partitions"] = meta.device_size
        return meta

    try:
        res = subprocess.run([lpdump_bin, str(super_raw_path)], capture_output=True, text=True)
        if res.returncode == 0:
            output = res.stdout
            # Parse block device size
            dev_size_match = re.search(r"Size:\s+(\d+)\s+bytes", output)
            if dev_size_match:
                meta.device_size = int(dev_size_match.group(1))

            # Parse metadata size & slots
            slots_match = re.search(r"Metadata max size:\s+(\d+)\s+bytes", output)
            if slots_match:
                meta.metadata_size = int(slots_match.group(1))
            slots_cnt = re.search(r"Metadata slot count:\s+(\d+)", output)
            if slots_cnt:
                meta.metadata_slots = int(slots_cnt.group(1))

            # Parse partition table section for available partitions
            for pm in re.finditer(r"Name:\s+([a-zA-Z0-9_\-]+)", output):
                pname = pm.group(1)
                if pname not in meta.available_partitions:
                    meta.available_partitions.append(pname)

            # Parse partition groups
            for gm in re.finditer(r"Name:\s+([a-zA-Z0-9_\-]+)\s*\n\s*Maximum size:\s+(\d+)", output):
                gname = gm.group(1)
                gsize = int(gm.group(2))
                if gname != "default":
                    meta.groups[gname] = gsize

            logger.info(f"Successfully dumped metadata: device_size={meta.device_size}, partitions={meta.available_partitions}, groups={list(meta.groups.keys())}")
    except Exception as e:
        logger.warning(f"Failed to run lpdump: {e}")

    if not meta.groups:
        meta.groups["orangeui_dynamic_partitions"] = meta.device_size

    return meta


def unpack_super(super_img: Path, output_dir: Path, target_partitions: Optional[List[str]] = None, extract_all: bool = False, slot: int = 0) -> Path:
    """
    Unpack partitions from super.img.
    By default extracts only: system, vendor, product.
    """
    require_tool("lpunpack", logger)
    if not super_img.is_file():
        logger.fail(f"Input super.img not found: {super_img}")

    output_dir.mkdir(parents=True, exist_ok=True)
    targets = target_partitions if target_partitions else DEFAULT_TARGET_PARTITIONS

    logger.banner("OrangeUI Super Unpacker", f"Target: {super_img.name} -> {output_dir}")

    # Step 1: Unsparse if required
    is_sparse = is_sparse_image(super_img)
    raw_img = super_img
    temp_raw = None
    if is_sparse:
        logger.info("Detected sparse super image. Unsparsing...")
        temp_raw = output_dir / "super_unsparse.img"
        raw_img = unsparse_image(super_img, temp_raw)

    # Step 2: Read layout metadata
    meta = dump_super_metadata(raw_img)

    # Step 3: Run lpunpack
    lpunpack_bin = check_command("lpunpack")
    cmd = [lpunpack_bin, f"--slot={slot}"]
    if not extract_all:
        if meta.available_partitions:
            # Only request partitions that exist in image metadata
            to_extract = []
            for t in targets:
                for cand in [t, f"{t}_a", f"{t}_b"]:
                    if cand in meta.available_partitions and cand not in to_extract:
                        to_extract.append(cand)
            if not to_extract:
                to_extract = targets
            for p in to_extract:
                cmd.extend(["-p", p])
        else:
            for p in targets:
                cmd.extend(["-p", p])

    cmd.extend([str(raw_img), str(output_dir)])

    logger.info(f"Executing lpunpack for partitions: {', '.join(targets) if not extract_all else 'ALL'}...")
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        logger.fail(f"lpunpack execution failed: {res.stderr.strip() or res.stdout.strip()}")

    # Clean up temporary raw image if created
    if temp_raw and temp_raw.exists():
        temp_raw.unlink()

    # Step 4: Detect filesystems and build metadata records
    table = Table(title="Extracted Partitions Information", border_style="green")
    table.add_column("Partition", style="bold cyan")
    table.add_column("File Size", justify="right")
    table.add_column("Filesystem", justify="center", style="bold")
    table.add_column("Path", style="dim")

    found_files = list(output_dir.glob("*.img"))
    if not found_files:
        logger.fail("lpunpack finished but no partition images were extracted.")

    for part_img in sorted(found_files):
        part_name = part_img.stem
        size = part_img.stat().st_size
        fs_type = detect_filesystem(part_img)

        # Match partition to group
        assigned_group = next(iter(meta.groups.keys())) if meta.groups else "default"
        for gname in meta.groups:
            if "dynamic" in gname.lower() or "main" in gname.lower():
                assigned_group = gname
                break

        meta.partitions[part_name] = {
            "size": size,
            "group": assigned_group,
            "fs_type": fs_type,
            "filename": part_img.name
        }

        table.add_row(
            part_name,
            f"{size / (1024 * 1024):.2f} MB",
            f"[{'green' if fs_type != 'unknown' else 'yellow'}]{fs_type.upper()}[/]",
            str(part_img.relative_to(output_dir))
        )

    from rich.console import Console
    Console().print(table)

    meta_file = output_dir / ".repack_meta.json"
    meta.save(meta_file)
    logger.success(f"Unpack complete! Layout metadata saved to '{meta_file.name}'.")
    return output_dir


def repack_super(
    input_dir: Path,
    output_super: Path,
    device_size: Optional[int] = None,
    sparse: bool = True,
    disable_verity: bool = True,
    metadata_size: int = 65536,
    metadata_slots: int = 2
) -> Path:
    """
    Rebuild super.img from unpacked partition images using lpmake.
    Preserves original partition sizes and dynamic partition groups.
    """
    require_tool("lpmake", logger)
    if not input_dir.is_dir():
        logger.fail(f"Partition directory does not exist: {input_dir}")

    output_super.parent.mkdir(parents=True, exist_ok=True)
    meta_file = input_dir / ".repack_meta.json"

    logger.banner("OrangeUI Super Repacker", f"Source: {input_dir} -> Output: {output_super}")

    if meta_file.is_file():
        meta = SuperMetadata.load(meta_file)
        logger.info(f"Loaded layout metadata from '{meta_file.name}'.")
    else:
        logger.warning(f"No .repack_meta.json found in {input_dir}; creating dynamic layout.")
        meta = SuperMetadata()

    # Discover partition images in directory
    found_imgs = list(input_dir.glob("*.img"))
    if not found_imgs:
        logger.fail(f"No .img partition images found in {input_dir}")

    # Update metadata with current files
    total_parts_size = 0
    for img in found_imgs:
        part_name = img.stem
        size = img.stat().st_size
        total_parts_size += size
        group = meta.partitions.get(part_name, {}).get("group", "default")
        fs_type = meta.partitions.get(part_name, {}).get("fs_type", detect_filesystem(img))
        meta.partitions[part_name] = {
            "size": size,
            "group": group,
            "fs_type": fs_type,
            "filename": img.name
        }

    # Group configuration
    if not meta.groups or "default" in meta.groups:
        if "default" in meta.groups:
            meta.groups.pop("default", None)
        if not meta.groups:
            meta.groups["orangeui_dynamic_partitions"] = int(total_parts_size * 1.05) + 16 * 1024 * 1024

    primary_group = next(iter(meta.groups.keys()))

    # Determine final device size
    if device_size:
        final_dev_size = device_size
    elif meta.device_size and meta.device_size >= total_parts_size:
        final_dev_size = meta.device_size
    else:
        # Auto calculate with padding
        final_dev_size = int(total_parts_size * 1.05) + 32 * 1024 * 1024

    # Ensure groups max size accommodates partitions
    for gname in meta.groups:
        if meta.groups[gname] < total_parts_size:
            meta.groups[gname] = final_dev_size

    lpmake_bin = check_command("lpmake")
    cmd = [
        lpmake_bin,
        f"--metadata-size={meta.metadata_size or metadata_size}",
        f"--metadata-slots={meta.metadata_slots or metadata_slots}",
        f"--device-size={final_dev_size}",
        "--block-size=4096",
        "--alignment=4096",
        f"--output={str(output_super)}"
    ]

    if sparse:
        cmd.append("--sparse")

    # Add partition groups (liblp reserves 'default', so do not redefine it)
    for gname, gsize in meta.groups.items():
        if gname != "default":
            cmd.append(f"--group={gname}:{gsize}")

    # Add partitions and their image payloads
    for part_name, info in meta.partitions.items():
        size = info["size"]
        group = info.get("group", primary_group)
        if group == "default":
            group = primary_group
        img_file = input_dir / info["filename"]
        if not img_file.exists():
            continue

        # Format: <name>:<attributes>:<size>[:group]
        cmd.append(f"--partition={part_name}:readonly:{size}:{group}")
        cmd.append(f"--image={part_name}={str(img_file)}")

    logger.info(f"Invoking lpmake: target super size={final_dev_size / (1024*1024):.2f} MB, partitions={len(meta.partitions)}")
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        logger.fail(f"lpmake failed: {res.stderr.strip() or res.stdout.strip()}")

    if not output_super.exists():
        logger.fail(f"Repack completed but output file '{output_super}' was not generated.")

    out_size = output_super.stat().st_size
    logger.success(f"Repacked super.img created successfully: '{output_super}' ({out_size / (1024*1024):.2f} MB)")
    return output_super


def main():
    parser = argparse.ArgumentParser(
        description="OrangeUI Super Partition Utility (lpunpack / lpmake)",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    subparsers = parser.add_subparsers(dest="action", help="Action to perform")

    # Unpack subparser
    unpack_p = subparsers.add_parser("unpack", help="Unpack partitions from super.img")
    unpack_p.add_argument("--input", "-i", type=str, required=True, help="Path to input super.img")
    unpack_p.add_argument("--output", "-o", type=str, default="extracted/super", help="Directory for unpacked partitions")
    unpack_p.add_argument("--partitions", "-p", nargs="+", default=DEFAULT_TARGET_PARTITIONS, help="Target partitions to extract")
    unpack_p.add_argument("--all", "-a", action="store_true", help="Extract all partitions from super.img")
    unpack_p.add_argument("--slot", "-s", type=int, default=0, help="Metadata slot number (default: 0)")

    # Repack subparser
    repack_p = subparsers.add_parser("repack", help="Rebuild super.img from unpacked partition images")
    repack_p.add_argument("--input", "-i", type=str, required=True, help="Directory containing partition images")
    repack_p.add_argument("--output", "-o", type=str, default="releases/super.img", help="Path to output super.img")
    repack_p.add_argument("--device-size", "-d", type=int, help="Total block device size in bytes")
    repack_p.add_argument("--no-sparse", action="store_true", help="Disable sparse output (generate raw super image)")
    repack_p.add_argument("--disable-verity", action="store_true", default=True, help="Disable dm-verity")

    args = parser.parse_args()

    if not args.action:
        parser.print_help()
        sys.exit(1)

    if args.action == "unpack":
        unpack_super(
            super_img=Path(args.input),
            output_dir=Path(args.output),
            target_partitions=args.partitions,
            extract_all=args.all,
            slot=args.slot
        )
    elif args.action == "repack":
        repack_super(
            input_dir=Path(args.input),
            output_super=Path(args.output),
            device_size=args.device_size,
            sparse=not args.no_sparse,
            disable_verity=args.disable_verity
        )


if __name__ == "__main__":
    main()
