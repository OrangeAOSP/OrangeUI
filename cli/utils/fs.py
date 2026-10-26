#!/usr/bin/env python3
"""
OrangeUI Filesystem and Partition Image Utilities
Handles sparse image conversion, FS detection (EXT4, EROFS, F2FS),
and partition extraction/repacking.
"""

import os
import shutil
import struct
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from cli.utils.deps import check_command
from cli.utils.logger import get_logger

logger = get_logger("FS_UTILS")

SPARSE_HEADER_MAGIC = 0xED26FF3A
EXT4_SUPER_OFFSET = 1024
EXT4_MAGIC = 0xEF53
EROFS_MAGIC = 0xE0F5E1E2
F2FS_MAGIC = 0xF2F52010


def is_sparse_image(image_path: Path) -> bool:
    """Check if the given file has Android sparse image magic."""
    if not image_path.is_file() or image_path.stat().st_size < 28:
        return False
    try:
        with open(image_path, "rb") as f:
            magic = struct.unpack("<I", f.read(4))[0]
            return magic == SPARSE_HEADER_MAGIC
    except Exception:
        return False


def unsparse_image(src_path: Path, dst_path: Optional[Path] = None) -> Path:
    """Convert sparse image to raw image using simg2img if needed."""
    if not is_sparse_image(src_path):
        return src_path

    if dst_path is None:
        dst_path = src_path.with_name(src_path.stem + "_raw.img")

    simg2img_bin = check_command("simg2img")
    if not simg2img_bin:
        logger.fail("File is an Android sparse image, but 'simg2img' is not installed.")

    logger.info(f"Converting sparse image '{src_path.name}' to raw image '{dst_path.name}'...")
    res = subprocess.run([simg2img_bin, str(src_path), str(dst_path)], capture_output=True, text=True)
    if res.returncode != 0:
        logger.fail(f"simg2img failed: {res.stderr.strip()}")

    return dst_path


def sparse_image(src_path: Path, dst_path: Path) -> Path:
    """Convert raw image to sparse image using img2simg."""
    img2simg_bin = check_command("img2simg")
    if not img2simg_bin:
        logger.fail("'img2simg' is required to create sparse images.")

    logger.info(f"Converting raw image '{src_path.name}' to sparse image '{dst_path.name}'...")
    res = subprocess.run([img2simg_bin, str(src_path), str(dst_path)], capture_output=True, text=True)
    if res.returncode != 0:
        logger.fail(f"img2simg failed: {res.stderr.strip()}")

    return dst_path


def detect_filesystem(image_path: Path) -> str:
    """
    Detect the filesystem of an Android partition image.
    Supports EXT4, EROFS, F2FS.
    """
    if not image_path.is_file():
        return "unknown"

    # If sparse, inspect temporary raw or check with file command
    if is_sparse_image(image_path):
        # We can detect via file utility or unsparse
        file_bin = check_command("file")
        if file_bin:
            res = subprocess.run([file_bin, "-b", str(image_path)], capture_output=True, text=True)
            output = res.stdout.lower()
            if "ext4" in output:
                return "ext4"
            if "erofs" in output:
                return "erofs"
            if "f2fs" in output:
                return "f2fs"

    try:
        size = image_path.stat().st_size
        if size < 2048:
            return "unknown"

        with open(image_path, "rb") as f:
            # Check EXT4: Superblock at 1024, magic at offset +0x38 (1080)
            f.seek(1080)
            ext4_magic = struct.unpack("<H", f.read(2))[0]
            if ext4_magic == EXT4_MAGIC:
                return "ext4"

            # Check EROFS: Superblock at 1024, magic at offset 1024
            f.seek(1024)
            erofs_magic = struct.unpack("<I", f.read(4))[0]
            if erofs_magic == EROFS_MAGIC:
                return "erofs"

            # Check F2FS: Superblock at 1024, magic at offset 1024
            f.seek(1024)
            f2fs_magic = struct.unpack("<I", f.read(4))[0]
            if f2fs_magic == F2FS_MAGIC:
                return "f2fs"

    except Exception as e:
        logger.debug(f"Error inspecting image header {image_path}: {e}")

    # Fallback to `file` command
    file_bin = check_command("file")
    if file_bin:
        res = subprocess.run([file_bin, "-b", str(image_path)], capture_output=True, text=True)
        out = res.stdout.lower()
        if "ext4" in out:
            return "ext4"
        if "erofs" in out:
            return "erofs"
        if "f2fs" in out:
            return "f2fs"

    return "unknown"


def extract_ext4_image(image_path: Path, output_dir: Path, subpath: str = "/") -> bool:
    """
    Extract files from an EXT4 image using debugfs without requiring root privileges.
    """
    debugfs_bin = check_command("debugfs")
    if not debugfs_bin:
        logger.error("'debugfs' is not available to extract ext4 image.")
        return False

    output_dir.mkdir(parents=True, exist_ok=True)
    # debugfs command: rdump <src_path_in_fs> <dest_dir_on_host>
    cmd = [debugfs_bin, "-R", f"rdump {subpath} {str(output_dir)}", str(image_path)]
    logger.info(f"Extracting ext4 files from {image_path.name} via debugfs...")
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0 and not any(output_dir.iterdir()):
        logger.error(f"debugfs extraction failed: {res.stderr.strip() or res.stdout.strip()}")
        return False
    return True


def extract_erofs_image(image_path: Path, output_dir: Path) -> bool:
    """
    Extract files from an EROFS image using fsck.erofs or dump.erofs or 7z.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    
    fsck_bin = check_command("fsck.erofs")
    if fsck_bin:
        cmd = [fsck_bin, f"--extract={str(output_dir)}", "--overwrite", str(image_path)]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0:
            return True

    dump_bin = check_command("dump.erofs")
    if dump_bin:
        cmd = [dump_bin, f"--extract={str(output_dir)}", str(image_path)]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0:
            return True

    seven_z = check_command("7z") or check_command("7za")
    if seven_z:
        cmd = [seven_z, "x", f"-o{str(output_dir)}", str(image_path), "-y"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0:
            return True

    logger.warning("Could not find standard EROFS extractor (fsck.erofs/dump.erofs/7z).")
    return False


def build_ext4_image(source_dir: Path, output_img: Path, partition_size: int, mount_point: str = "/system", file_contexts: Optional[Path] = None) -> bool:
    """
    Build an EXT4 filesystem image using mke2fs and e2fsdroid without requiring root.
    """
    mke2fs_bin = check_command("mke2fs")
    e2fsdroid_bin = check_command("e2fsdroid")

    if not mke2fs_bin or not e2fsdroid_bin:
        logger.error("Building ext4 requires 'mke2fs' and 'e2fsdroid'.")
        return False

    output_img.parent.mkdir(parents=True, exist_ok=True)
    if output_img.exists():
        output_img.unlink()

    block_size = 4096
    blocks_count = partition_size // block_size

    # Step 1: Format empty ext4 image
    mke2fs_cmd = [
        mke2fs_bin,
        "-O", "^has_journal",
        "-b", str(block_size),
        "-m", "0",
        "-t", "ext4",
        "-L", mount_point.lstrip("/"),
        str(output_img),
        str(blocks_count)
    ]
    res1 = subprocess.run(mke2fs_cmd, capture_output=True, text=True)
    if res1.returncode != 0:
        logger.error(f"mke2fs failed: {res1.stderr.strip()}")
        return False

    # Step 2: Inject source files with e2fsdroid
    e2fs_cmd = [
        e2fsdroid_bin,
        "-e",
        "-a", mount_point,
    ]
    if file_contexts and file_contexts.is_file():
        e2fs_cmd.extend(["-S", str(file_contexts)])
    e2fs_cmd.extend(["-f", str(source_dir), str(output_img)])

    res2 = subprocess.run(e2fs_cmd, capture_output=True, text=True)
    if res2.returncode != 0:
        logger.error(f"e2fsdroid failed: {res2.stderr.strip()}")
        return False

    return True


def get_dir_size(path: Path) -> int:
    """Calculate total size of all files in a directory."""
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            fp = Path(root) / f
            if not fp.is_symlink() and fp.exists():
                total += fp.stat().st_size
    return total
