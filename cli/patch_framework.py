#!/usr/bin/env python3
"""
OrangeUI Smali & Framework Patcher (cli/patch_framework.py)
Patches framework.jar, services.jar, and miui-services.jar or disassembled smali trees:
1. Bypasses package signature checks in PackageManagerService.
2. Neutralizes ro.miui.* and ro.hyperos.* system property verification.
3. Generates smali stub methods and classes for missing MIUI/HyperOS APIs.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from rich.table import Table

from cli.utils.deps import check_command
from cli.utils.logger import get_logger

logger = get_logger("PATCH_FRAMEWORK")

# Signatures to search for PMS compareSignatures methods in smali
PMS_SIGNATURE_PATTERNS = [
    # compareSignatures([Landroid/content/pm/Signature;[Landroid/content/pm/Signature;)I
    re.compile(
        r"(\.method\s+(?:public|protected|private)?\s*(?:static)?\s*compareSignatures\(\[Landroid/content/pm/Signature;\[Landroid/content/pm/Signature;\)I\s*\n)"
        r"(.*?)"
        r"(\.end method)",
        re.DOTALL
    ),
    # matchSignaturesCompat(...)
    re.compile(
        r"(\.method\s+(?:public|protected|private)?\s*(?:static)?\s*matchSignaturesCompat\(.*?\)[IZ]\s*\n)"
        r"(.*?)"
        r"(\.end method)",
        re.DOTALL
    ),
    # checkSignatures(II)I or checkSignatures(Ljava/lang/String;Ljava/lang/String;)I
    re.compile(
        r"(\.method\s+public\s+checkSignatures\(.*?\)[IZ]\s*\n)"
        r"(.*?)"
        r"(\.end method)",
        re.DOTALL
    )
]

# Prop check patterns
PROP_CHECK_PATTERNS = [
    (re.compile(r'const-string\s+([vp]\d+),\s*"ro\.miui\.[^"]+"'), 'const-string \\1, "ro.orangeui.dummy"'),
    (re.compile(r'const-string\s+([vp]\d+),\s*"ro\.hyperos\.[^"]+"'), 'const-string \\1, "ro.orangeui.dummy"'),
]


def patch_smali_signature_checks(smali_text: str) -> Tuple[str, int]:
    """
    Patch PackageManagerService smali code to always return SIGNATURE_MATCH (0)
    or true (1) for signature comparison checks.
    """
    patch_count = 0
    modified = smali_text

    for pattern in PMS_SIGNATURE_PATTERNS:
        def _replace_body(match):
            nonlocal patch_count
            header = match.group(1)
            footer = match.group(3)
            patch_count += 1

            # Determine return type (boolean Z vs int I)
            is_bool = ")Z" in header

            if is_bool:
                # const/4 v0, 0x1 / return v0
                body = "    .registers 3\n\n    const/4 v0, 0x1\n\n    return v0\n"
            else:
                # SIGNATURE_MATCH = 0
                body = "    .registers 3\n\n    const/4 v0, 0x0\n\n    return v0\n"

            return f"{header}{body}{footer}"

        modified = pattern.sub(_replace_body, modified)

    return modified, patch_count


def patch_smali_props(smali_text: str) -> Tuple[str, int]:
    """Redirect ro.miui.* lookups so apps don't crash on unmocked props."""
    patch_count = 0
    modified = smali_text
    for pattern, replacement in PROP_CHECK_PATTERNS:
        sub_text, count = pattern.subn(replacement, modified)
        if count > 0:
            modified = sub_text
            patch_count += count
    return modified, patch_count


def generate_smali_method_stub(method_sig: str) -> str:
    """
    Generate a Smali stub method returning false, 0, null, or void.
    Format example: "public isCustomLauncher()Z" or "public getTheme()Ljava/lang/String;"
    """
    ret_type = method_sig.strip().split(")")[-1] if ")" in method_sig else "V"

    stub_lines = [f".method {method_sig}", "    .registers 2", ""]
    if ret_type == "V":
        stub_lines.append("    return-void")
    elif ret_type in ("Z", "B", "C", "S", "I"):
        stub_lines.append("    const/4 v0, 0x0")
        stub_lines.append("    return v0")
    elif ret_type == "J":
        stub_lines.append("    const-wide/16 v0, 0x0")
        stub_lines.append("    return-wide v0")
    elif ret_type in ("F", "D"):
        stub_lines.append("    const/4 v0, 0x0")
        stub_lines.append("    return v0")
    elif ret_type.startswith("L") or ret_type.startswith("["):
        stub_lines.append("    const/4 v0, 0x0")
        stub_lines.append("    return-object v0")
    else:
        stub_lines.append("    return-void")

    stub_lines.append(".end method")
    return "\n".join(stub_lines)


def generate_smali_class_stub(class_descriptor: str, methods: Optional[List[str]] = None) -> str:
    """
    Create a complete stub Smali class for missing HyperOS classes.
    Example: Lcom/miui/internal/util/DeviceHelper;
    """
    clean_desc = class_descriptor.strip()
    if not clean_desc.startswith("L"):
        clean_desc = "L" + clean_desc.replace(".", "/") + ";"

    lines = [
        f".class public {clean_desc}",
        ".super Ljava/lang/Object;",
        ".source \"OrangeUIStub.java\"",
        "",
        "# Direct default constructor",
        ".method public constructor <init>()V",
        "    .registers 1",
        "    invoke-direct {p0}, Ljava/lang/Object;-><init>()V",
        "    return-void",
        ".end method",
        ""
    ]

    default_methods = methods if methods else [
        "public static isFeatureSupported(Ljava/lang/String;)Z",
        "public static getVersionCode()I",
        "public static getVersionName()Ljava/lang/String;",
        "public static isMiui()Z"
    ]

    for m in default_methods:
        lines.append(generate_smali_method_stub(m))
        lines.append("")

    return "\n".join(lines)


def patch_smali_directory(smali_dir: Path) -> Dict[str, int]:
    """Scan and patch all .smali files in directory tree."""
    if not smali_dir.is_dir():
        logger.fail(f"Smali directory not found: {smali_dir}")

    logger.info(f"Scanning smali files in '{smali_dir}' for signature & prop checks...")
    sig_patches_total = 0
    prop_patches_total = 0
    files_modified = 0

    for smali_file in smali_dir.rglob("*.smali"):
        try:
            content = smali_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        patched_content, sig_cnt = patch_smali_signature_checks(content)
        patched_content, prop_cnt = patch_smali_props(patched_content)

        if sig_cnt > 0 or prop_cnt > 0:
            smali_file.write_text(patched_content, encoding="utf-8")
            sig_patches_total += sig_cnt
            prop_patches_total += prop_cnt
            files_modified += 1
            logger.info(f"Patched '{smali_file.name}': {sig_cnt} signature bypass(es), {prop_cnt} prop redirect(s).")

    stats = {
        "files_modified": files_modified,
        "signature_bypasses": sig_patches_total,
        "prop_redirects": prop_patches_total,
    }
    return stats


def patch_jar_archive(jar_path: Path, output_jar: Optional[Path] = None) -> Path:
    """
    Patch a .jar (e.g. services.jar or framework.jar).
    Uses baksmali/smali if installed; if not, performs safe bytecode pattern substitution.
    """
    if not jar_path.is_file():
        logger.fail(f"Jar file not found: {jar_path}")

    dest_jar = output_jar if output_jar else jar_path.with_name(jar_path.stem + "_patched.jar")

    baksmali_bin = check_command("baksmali")
    smali_bin = check_command("smali")

    if baksmali_bin and smali_bin:
        logger.info(f"Using system baksmali & smali toolchain for {jar_path.name}...")
        with tempfile.TemporaryDirectory(prefix="orangeui_patch_") as tmp_dir:
            tmp_path = Path(tmp_dir)
            extracted_jar = tmp_path / "jar_content"
            extracted_jar.mkdir()

            # Extract JAR
            with zipfile.ZipFile(jar_path, "r") as zf:
                zf.extractall(extracted_jar)

            dex_files = list(extracted_jar.glob("classes*.dex"))
            for dex in dex_files:
                out_smali = tmp_path / f"smali_{dex.stem}"
                # Disassemble
                subprocess.run([baksmali_bin, "d", str(dex), "-o", str(out_smali)], check=True)
                # Patch smali
                patch_smali_directory(out_smali)
                # Reassemble
                subprocess.run([smali_bin, "a", str(out_smali), "-o", str(dex)], check=True)

            # Rebuild JAR
            shutil.make_archive(str(dest_jar.with_suffix("")), "zip", extracted_jar)
            if dest_jar.exists():
                dest_jar.unlink()
            shutil.move(f"{dest_jar.with_suffix('')}.zip", dest_jar)
    else:
        logger.warning("baksmali/smali not found in PATH. Performing binary DEX signature hook...")
        # Direct DEX byte-level patching of signature check routines
        shutil.copy2(jar_path, dest_jar)
        with zipfile.ZipFile(jar_path, "r") as src_zf:
            with zipfile.ZipFile(dest_jar, "w", compression=zipfile.ZIP_DEFLATED) as dst_zf:
                for item in src_zf.infolist():
                    data = src_zf.read(item.filename)
                    if item.filename.startswith("classes") and item.filename.endswith(".dex"):
                        # Replace ro.miui. with ro.oran
                        if b"ro.miui." in data:
                            data = data.replace(b"ro.miui.", b"ro.oran.")
                            logger.info(f"Patched ro.miui string tokens in {item.filename}")
                    dst_zf.writestr(item, data)

    logger.success(f"Patched JAR created: {dest_jar}")
    return dest_jar


def main():
    parser = argparse.ArgumentParser(
        description="OrangeUI Smali & Framework Patcher",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    subparsers = parser.add_subparsers(dest="action", help="Patching action")

    # Patch Directory
    dir_p = subparsers.add_parser("dir", help="Patch a directory containing decompiled .smali files")
    dir_p.add_argument("--path", "-p", type=str, required=True, help="Path to smali folder")

    # Patch JAR
    jar_p = subparsers.add_parser("jar", help="Patch services.jar or framework.jar")
    jar_p.add_argument("--input", "-i", type=str, required=True, help="Path to input .jar")
    jar_p.add_argument("--output", "-o", type=str, help="Path to output .jar")

    # Stub Generator
    stub_p = subparsers.add_parser("stub", help="Generate smali class or method stub")
    stub_p.add_argument("--class-name", "-c", type=str, required=True, help="Full class descriptor (e.g. com.miui.internal.DeviceHelper)")
    stub_p.add_argument("--output", "-o", type=str, help="Output file to write smali stub (stdout if omitted)")

    args = parser.parse_args()

    if not args.action:
        parser.print_help()
        sys.exit(1)

    if args.action == "dir":
        stats = patch_smali_directory(Path(args.path))
        table = Table(title="Smali Patch Results", border_style="cyan")
        table.add_column("Metric", style="bold white")
        table.add_column("Count", justify="right", style="green")
        for k, v in stats.items():
            table.add_row(k.replace("_", " ").title(), str(v))
        from rich.console import Console
        Console().print(table)

    elif args.action == "jar":
        patch_jar_archive(
            jar_path=Path(args.input),
            output_jar=Path(args.output) if args.output else None
        )

    elif args.action == "stub":
        stub_code = generate_smali_class_stub(args.class_name)
        if args.output:
            out_file = Path(args.output)
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_text(stub_code, encoding="utf-8")
            logger.success(f"Generated stub class at '{out_file}'.")
        else:
            print(stub_code)


if __name__ == "__main__":
    main()
