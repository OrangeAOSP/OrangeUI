#!/usr/bin/env python3
"""
OrangeUI Central Pipeline & Cleanup/Compaction Tool (cli/pipeline.py)

Supported Flags:
  --line                     Run full pipeline end-to-end:
                             (Unpack super -> Extract HyperOS -> Patch Framework -> Inject & Build)
  --clear=all|raw|out        Clean cached and temporary files:
                             - all: remove all cache, extracted files, raw images, and outputs
                             - raw: remove only raw unsparsed images (*_raw.img, super_unsparse.img)
                             - out: remove extracted output APKs, JARs, and built release artifacts
  --compact-gzip=all|out     Package files into .tar.gz archive
  --comapct-gzip=all|out     (Alias for compact-gzip)
  --compact-tar=all|out      Package files into uncompressed .tar archive
  --compact-xz=all|out       Package files into high-compression .tar.xz archive (preset 9)
"""

import argparse
import os
import shutil
import sys
import tarfile
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from rich.progress import BarColumn, Progress, TextColumn, TimeRemainingColumn

from cli.charoite_builder import build_charoite
from cli.extract_hyperos import extract_hyperos_apps
from cli.manifest_parser import ManifestParser
from cli.patch_framework import patch_smali_directory
from cli.repack_super import repack_super, unpack_super
from cli.utils.deps import print_dependency_table
from cli.utils.logger import get_logger

logger = get_logger("PIPELINE")


# ============================================================================
# 1. CLEANUP UTILITIES (--clear=all|raw|out)
# ============================================================================

def clear_cache(target: str) -> None:
    """
    Remove temporary, raw, or output files based on target:
    - all: clean all caches, raw images, unpacked directories, releases
    - raw: clean only raw images (*_raw.img, super_unsparse.img)
    - out: clean output APKs, JARs, and release artifacts
    """
    target = target.lower().strip()
    logger.banner(f"OrangeUI Cache Cleaner", f"Mode: --clear={target}")

    removed_count = 0
    reclaimed_bytes = 0

    def _delete_file(p: Path):
        nonlocal removed_count, reclaimed_bytes
        try:
            if p.is_file() or p.is_symlink():
                sz = p.stat().st_size
                p.unlink()
                removed_count += 1
                reclaimed_bytes += sz
                logger.debug(f"Removed file: {p}")
        except Exception as e:
            logger.warning(f"Could not delete {p}: {e}")

    def _delete_dir_contents(d: Path, keep_gitkeep: bool = True):
        nonlocal removed_count, reclaimed_bytes
        if not d.is_dir():
            return
        for item in list(d.iterdir()):
            if keep_gitkeep and item.name == ".gitkeep":
                continue
            try:
                if item.is_dir():
                    shutil.rmtree(item)
                    removed_count += 1
                    logger.debug(f"Removed directory: {item}")
                else:
                    sz = item.stat().st_size
                    item.unlink()
                    removed_count += 1
                    reclaimed_bytes += sz
                    logger.debug(f"Removed file: {item}")
            except Exception as e:
                logger.warning(f"Could not delete {item}: {e}")

    if target == "raw":
        # Delete only raw unsparse images across workspace
        raw_patterns = ["*_raw.img", "*_unsparse.img", "super_unsparse.img", "*raw*.img"]
        search_dirs = [
            REPO_ROOT / "extracted",
            REPO_ROOT / "inject",
            REPO_ROOT / "releases",
            Path("/mnt/loopfox/phones/work_charoite")
        ]
        for sdir in search_dirs:
            if sdir.is_dir():
                for pat in raw_patterns:
                    for f in sdir.rglob(pat):
                        _delete_file(f)
        logger.success(f"Cleaned RAW images: {removed_count} files ({reclaimed_bytes / (1024*1024):.1f} MB freed).")

    elif target == "out":
        # Delete extracted APKs, JARs in inject, and releases/
        inject_dir = REPO_ROOT / "inject"
        if inject_dir.is_dir():
            for apk in inject_dir.glob("*.apk"):
                _delete_file(apk)
            if (inject_dir / "lib64").is_dir():
                _delete_dir_contents(inject_dir / "lib64")
            if (inject_dir / "framework").is_dir():
                _delete_dir_contents(inject_dir / "framework")

        releases_dir = REPO_ROOT / "releases"
        for ext in ["*.img", "*.zip", "*.tar", "*.gz", "*.xz"]:
            for f in releases_dir.glob(ext):
                _delete_file(f)

        charoite_rel = releases_dir / "charoite"
        if charoite_rel.is_dir():
            _delete_dir_contents(charoite_rel)

        logger.success(f"Cleaned OUT artifacts: {removed_count} items ({reclaimed_bytes / (1024*1024):.1f} MB freed).")

    elif target == "all":
        # Clean everything: raw images, extracted partitions, donor roots, releases cache, and outputs
        # 1. Clean raw images
        for pat in ["*_raw.img", "*_unsparse.img", "super_unsparse.img"]:
            for f in REPO_ROOT.rglob(pat):
                _delete_file(f)

        # 2. Clean extracted/
        _delete_dir_contents(REPO_ROOT / "extracted")

        # 3. Clean temporary donor roots
        _delete_dir_contents(REPO_ROOT / "inject" / "_donor_root")

        # 4. Clean releases cache and outputs
        _delete_dir_contents(REPO_ROOT / "releases" / "cache")
        _delete_dir_contents(REPO_ROOT / "releases" / "charoite")
        for ext in ["*.img", "*.zip", "*.tar", "*.gz", "*.xz"]:
            for f in (REPO_ROOT / "releases").glob(ext):
                _delete_file(f)

        # 5. Clean inject APKs, lib64, framework
        inject_dir = REPO_ROOT / "inject"
        if inject_dir.is_dir():
            for apk in inject_dir.glob("*.apk"):
                _delete_file(apk)
            _delete_dir_contents(inject_dir / "lib64")
            _delete_dir_contents(inject_dir / "framework")

        logger.success(f"Full cleanup complete: {removed_count} items ({reclaimed_bytes / (1024*1024):.1f} MB freed).")

    else:
        logger.fail(f"Unknown clear target: '{target}'. Supported values: all, raw, out.")


# ============================================================================
# 2. COMPACT ARCHIVING (--compact-gzip / --compact-tar / --compact-xz)
# ============================================================================

def get_compact_file_list(scope: str) -> List[Tuple[Path, str]]:
    """
    Collect list of (absolute_path, arcname) to pack:
    - all: packs whole workspace deliverables (inject, extracted metadata, releases, docs)
    - out: packs only output APKs and JARs (from inject/ and inject/framework/)
    """
    file_list = []
    scope = scope.lower().strip()

    if scope == "out":
        # Only output APKs and JARs
        inject_dir = REPO_ROOT / "inject"
        if inject_dir.is_dir():
            for apk in sorted(inject_dir.glob("*.apk")):
                file_list.append((apk, f"apks/{apk.name}"))
            fw_dir = inject_dir / "framework"
            if fw_dir.is_dir():
                for jar in sorted(fw_dir.glob("*.jar")):
                    file_list.append((jar, f"framework/{jar.name}"))
            lib_dir = inject_dir / "lib64"
            if lib_dir.is_dir():
                for so in sorted(lib_dir.glob("*.so")):
                    file_list.append((so, f"lib64/{so.name}"))
            mf = inject_dir / "manifest.json"
            if mf.is_file():
                file_list.append((mf, "manifest.json"))

    elif scope == "all":
        # All resulting files and outputs
        for base in ["inject", "releases", "docs"]:
            base_dir = REPO_ROOT / base
            if base_dir.is_dir():
                for root, _, files in os.walk(base_dir):
                    for f in sorted(files):
                        fp = Path(root) / f
                        if fp.name.endswith(".log") or fp.name == ".gitkeep" or "super_unsparse" in fp.name:
                            continue
                        rel = fp.relative_to(REPO_ROOT).as_posix()
                        file_list.append((fp, rel))
        # Include README and manifest
        for top_f in ["README.md", "LICENSE"]:
            tf = REPO_ROOT / top_f
            if tf.is_file():
                file_list.append((tf, top_f))
    else:
        logger.fail(f"Invalid compact scope: '{scope}'. Supported: all, out.")

    return file_list


def create_compact_archive(format_type: str, scope: str, output_path: Optional[Path] = None) -> Path:
    """
    Package files into tar, tar.gz, or tar.xz:
    - format_type: 'gzip', 'tar', 'xz'
    - scope: 'all' or 'out'
    """
    format_type = format_type.lower().strip()
    scope = scope.lower().strip()

    ext_map = {
        "gzip": "tar.gz",
        "tar": "tar",
        "xz": "tar.xz"
    }
    mode_map = {
        "gzip": "w:gz",
        "tar": "w",
        "xz": "w:xz"
    }

    if format_type not in ext_map:
        logger.fail(f"Unsupported compact format: '{format_type}'. Supported: gzip, tar, xz.")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_ext = ext_map[format_type]
    
    compact_dir = REPO_ROOT / "releases" / "compact"
    compact_dir.mkdir(parents=True, exist_ok=True)

    if output_path:
        dest_archive = output_path
    else:
        dest_archive = compact_dir / f"OrangeUI_{scope}_{timestamp}.{archive_ext}"

    files_to_pack = get_compact_file_list(scope)
    if not files_to_pack:
        logger.fail(f"No files found to compact for scope: '{scope}'")

    logger.banner(f"OrangeUI Compactor ({format_type.upper()})", f"Scope: {scope} | Items: {len(files_to_pack)} -> {dest_archive.name}")

    tar_mode = mode_map[format_type]
    preset_kwargs = {"preset": 9} if format_type == "xz" else {}

    try:
        with tarfile.open(dest_archive, tar_mode, **preset_kwargs) as tar:
            with Progress(
                TextColumn("[bold cyan]{task.fields[action]}", justify="right"),
                BarColumn(),
                "[progress.percentage]{task.percentage:>3.1f}%",
                "•",
                TimeRemainingColumn()
            ) as progress:
                task = progress.add_task("packing", action=f"Compacting {format_type.upper()}", total=len(files_to_pack))
                for file_path, arcname in files_to_pack:
                    tar.add(file_path, arcname=arcname)
                    progress.update(task, advance=1)

    except Exception as e:
        if dest_archive.exists():
            dest_archive.unlink()
        logger.fail(f"Failed to create compact archive: {e}")

    out_sz = dest_archive.stat().st_size
    logger.success(f"Compact archive generated: '{dest_archive}' ({out_sz / (1024*1024):.2f} MB)")
    return dest_archive


# ============================================================================
# 3. FULL PIPELINE LINE EXECUTION (--line)
# ============================================================================

def run_line_pipeline(
    super_img_path: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    is_charoite: bool = True,
    version: str = "1.0"
) -> Path:
    """
    Executes the entire ROM modification chain seamlessly:
    Step 1: Unpack super.img (system, vendor, product, system_ext, mi_ext)
    Step 2: Extract HyperOS apps, native .so libs, and framework components
    Step 3: Validate and prepare injection manifest
    Step 4: Build OrangeUI release (GSI + MTK fixes + Fastboot ZIP)
    """
    logger.banner("🍊 OrangeUI Full Line Pipeline", f"Executing complete chain (Line Mode) | Version: {version}")

    # Step 1: Resolve super.img
    super_candidate = super_img_path
    if not super_candidate:
        for cand in [
            Path("/mnt/loopfox/phones/work_charoite/super.img"),
            Path("/mnt/loopfox/phones/charoite_global_images_OS3.0.304.0.WPFMIXM_16.0/images/super.img"),
            REPO_ROOT / "super.img"
        ]:
            if cand.is_file():
                super_candidate = cand
                break

    if not super_candidate or not super_candidate.is_file():
        logger.fail("No input super.img found for Line pipeline! Specify via --super.")

    # 1. Unpack super.img
    logger.step(1, 4, f"Unpacking Dynamic Partitions from '{super_candidate.name}'")
    extracted_super_dir = REPO_ROOT / "extracted" / "charoite"
    unpack_super(
        super_img=super_candidate,
        output_dir=extracted_super_dir,
        target_partitions=["system", "vendor", "product", "system_ext", "mi_ext"]
    )

    # 2. Extract HyperOS Applications & Frameworks
    logger.step(2, 4, "Extracting HyperOS System Apps, Libs, and Framework Components")
    inject_dir = REPO_ROOT / "inject"
    extract_hyperos_apps(
        source=extracted_super_dir,
        output_dir=inject_dir,
        include_libs=True,
        include_framework=True
    )

    # 3. Validate Manifest
    logger.step(3, 4, "Validating Injection Manifest & SELinux Rules")
    manifest_file = inject_dir / "manifest.json"
    manifest = ManifestParser.load(manifest_file)
    valid, errors = manifest.validate()
    if not valid:
        logger.fail(f"Manifest validation failed with {len(errors)} error(s).")

    # 4. Build Release Package
    logger.step(4, 4, f"Building Release Package for {'Redmi Note 15 Pro 4G (Charoite)' if is_charoite else 'Universal Treble'}")
    charoite_release_dir = output_dir if output_dir else (REPO_ROOT / "releases" / "charoite")
    final_artifact = build_charoite(
        payload_dir=Path("/mnt/loopfox/phones/charoite/Fabric/payload"),
        output_dir=charoite_release_dir,
        version=version
    )

    logger.success(f"🍊 Line Pipeline completed successfully! Release artifact: '{final_artifact}'")
    return final_artifact


# ============================================================================
# 4. CLI ENTRY POINT
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="OrangeUI Unified Line Pipeline, Cache Cleaner, and Compactor",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    # Line flag
    parser.add_argument("--line", action="store_true", help="Execute the entire chain at once (Line Mode)")

    # Clear flags
    parser.add_argument("--clear", type=str, choices=["all", "raw", "out"], help="Clean cache: 'all' (everything), 'raw' (unsparse images), 'out' (output APKs/JARs)")

    # Compact flags
    parser.add_argument("--compact-gzip", "--comapct-gzip", type=str, dest="compact_gzip", choices=["all", "out"], help="Compress into .tar.gz archive: 'all' or 'out'")
    parser.add_argument("--compact-tar", type=str, choices=["all", "out"], help="Package into uncompressed .tar archive: 'all' or 'out'")
    parser.add_argument("--compact-xz", type=str, choices=["all", "out"], help="Compress into .tar.xz (high compression) archive: 'all' or 'out'")

    # Configuration options
    parser.add_argument("--super", "-s", type=str, help="Path to input super.img for --line")
    parser.add_argument("--output", "-o", type=str, help="Output directory for generated artifacts")
    parser.add_argument("--version", "-v", type=str, default="1.0", help="Release version tag")
    parser.add_argument("--universal", action="store_true", help="Build universal GSI instead of Charoite")

    args = parser.parse_args()

    action_taken = False

    # 1. Clear flag
    if args.clear:
        clear_cache(args.clear)
        action_taken = True

    # 2. Compact flags
    if args.compact_gzip:
        create_compact_archive("gzip", args.compact_gzip, Path(args.output) if args.output else None)
        action_taken = True

    if args.compact_tar:
        create_compact_archive("tar", args.compact_tar, Path(args.output) if args.output else None)
        action_taken = True

    if args.compact_xz:
        create_compact_archive("xz", args.compact_xz, Path(args.output) if args.output else None)
        action_taken = True

    # 3. Line execution flag
    if args.line:
        super_p = Path(args.super) if args.super else None
        out_p = Path(args.output) if args.output else None
        run_line_pipeline(
            super_img_path=super_p,
            output_dir=out_p,
            is_charoite=not args.universal,
            version=args.version
        )
        action_taken = True

    if not action_taken:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    main()
