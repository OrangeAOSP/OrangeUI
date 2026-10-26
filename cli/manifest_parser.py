#!/usr/bin/env python3
"""
OrangeUI Manifest Parser
Parses, validates, and manages manifest.json for injecting APKs and libraries into ROMs.

Format:
{
  "OrangeUI_Settings.apk": "/system/priv-app/Settings/Settings.apk",
  "OrangeUI_Launcher.apk": "/system/priv-app/Launcher3/Launcher3.apk",
  "OrangeUI_SystemUI.apk": "/system/priv-app/SystemUI/SystemUI.apk",
  "lib64/libfoo.so": "/system/lib64/libfoo.so"
}
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from rich.table import Table

from cli.utils.logger import get_logger

logger = get_logger("MANIFEST")


class ManifestEntry:
    def __init__(self, source_rel_path: str, target_abs_path: str, source_full_path: Optional[Path] = None):
        self.source_rel = source_rel_path.lstrip("/")
        self.target_abs = "/" + target_abs_path.lstrip("/")
        self.source_path = source_full_path
        self.exists = self.source_path.exists() if self.source_path else False

    @property
    def is_apk(self) -> bool:
        return self.source_rel.lower().endswith(".apk")

    @property
    def is_so(self) -> bool:
        return self.source_rel.lower().endswith(".so")

    @property
    def is_overlay(self) -> bool:
        return "/overlay" in self.target_abs or "overlay" in self.source_rel.lower()


class ManifestData:
    def __init__(self, manifest_file: Path, entries: List[ManifestEntry], raw_data: Dict[str, Any]):
        self.manifest_file = manifest_file
        self.base_dir = manifest_file.parent
        self.entries = entries
        self.raw_data = raw_data

    @property
    def apks(self) -> List[ManifestEntry]:
        return [e for e in self.entries if e.is_apk]

    @property
    def shared_libs(self) -> List[ManifestEntry]:
        return [e for e in self.entries if e.is_so]

    @property
    def others(self) -> List[ManifestEntry]:
        return [e for e in self.entries if not e.is_apk and not e.is_so]

    def validate(self, strict: bool = True) -> Tuple[bool, List[str]]:
        """Validate whether all declared source files exist on disk."""
        errors = []
        for entry in self.entries:
            if not entry.exists:
                msg = f"Source file '{entry.source_rel}' declared in manifest does not exist in '{self.base_dir}'"
                errors.append(msg)
                if strict:
                    logger.error(msg)
        return (len(errors) == 0, errors)

    def print_table(self) -> None:
        table = Table(title=f"OrangeUI Injection Manifest ({self.manifest_file.name})", border_style="orange3")
        table.add_column("Type", justify="center", style="bold")
        table.add_column("Inject Source (Relative)", style="cyan")
        table.add_column("Target Path (in ROM)", style="green")
        table.add_column("Status", justify="center")

        for entry in self.entries:
            if entry.is_apk:
                type_badge = "[magenta]APK[/magenta]"
            elif entry.is_so:
                type_badge = "[blue]LIB64[/blue]" if "64" in entry.target_abs else "[blue]LIB[/blue]"
            else:
                type_badge = "[yellow]OTHER[/yellow]"

            status_badge = "[bold green]EXISTS[/bold green]" if entry.exists else "[bold red]MISSING[/bold red]"
            table.add_row(type_badge, entry.source_rel, entry.target_abs, status_badge)

        from rich.console import Console
        Console().print(table)


class ManifestParser:
    @staticmethod
    def load(manifest_path: Path) -> ManifestData:
        """Load and parse manifest.json from path."""
        if not manifest_path.is_file():
            logger.fail(f"Manifest file not found: {manifest_path}")

        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.fail(f"Invalid JSON in manifest '{manifest_path}': {e}")

        if not isinstance(data, dict):
            logger.fail(f"Manifest root must be a JSON object (dictionary), got {type(data).__name__}")

        base_dir = manifest_path.parent
        entries = []

        # Support standard format { "Source.apk": "/target/path.apk" }
        # as well as nested { "files": { ... } }
        file_map = data.get("files", data) if "files" in data and isinstance(data["files"], dict) else data

        for src, dst in file_map.items():
            if isinstance(dst, dict) and "target" in dst:
                target_path = dst["target"]
            elif isinstance(dst, str):
                target_path = dst
            else:
                continue

            full_src = base_dir / src
            entries.append(ManifestEntry(source_rel_path=src, target_abs_path=target_path, source_full_path=full_src))

        manifest = ManifestData(manifest_file=manifest_path, entries=entries, raw_data=data)
        logger.info(f"Loaded manifest with {len(entries)} entry/entries from '{manifest_path}'.")
        return manifest

    @staticmethod
    def generate_from_dir(inject_dir: Path, output_file: Optional[Path] = None) -> Path:
        """Scan inject directory and generate a template manifest.json."""
        if not inject_dir.is_dir():
            logger.fail(f"Inject directory does not exist: {inject_dir}")

        manifest_map = {}
        for item in inject_dir.rglob("*"):
            if item.is_file() and item.name != "manifest.json" and not item.name.endswith(".patch") and not item.name.endswith(".rule"):
                rel_path = item.relative_to(inject_dir).as_posix()
                if item.suffix == ".apk":
                    # Infer default destination
                    stem = item.stem
                    manifest_map[rel_path] = f"/system/priv-app/{stem}/{stem}.apk"
                elif item.suffix == ".so":
                    if "lib64" in rel_path or "arm64" in rel_path:
                        manifest_map[rel_path] = f"/system/lib64/{item.name}"
                    else:
                        manifest_map[rel_path] = f"/system/lib/{item.name}"
                else:
                    manifest_map[rel_path] = f"/system/etc/{item.name}"

        dest_file = output_file if output_file else (inject_dir / "manifest.json")
        try:
            with open(dest_file, "w", encoding="utf-8") as f:
                json.dump(manifest_map, f, indent=2)
            logger.success(f"Generated manifest with {len(manifest_map)} entries at '{dest_file}'.")
        except Exception as e:
            logger.fail(f"Failed to write manifest '{dest_file}': {e}")

        return dest_file


def main():
    parser = argparse.ArgumentParser(
        description="OrangeUI Manifest Parser & Validator",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--manifest", "-m", type=str, default="inject/manifest.json", help="Path to manifest.json")
    parser.add_argument("--validate", "-v", action="store_true", help="Validate source files existence strictly")
    parser.add_argument("--generate", "-g", type=str, help="Auto-generate manifest.json from target directory")
    parser.add_argument("--show", "-s", action="store_true", help="Display manifest entries in formatted table")

    args = parser.parse_args()

    if args.generate:
        gen_dir = Path(args.generate)
        out_file = Path(args.manifest) if args.manifest else (gen_dir / "manifest.json")
        ManifestParser.generate_from_dir(gen_dir, out_file)
        sys.exit(0)

    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        logger.fail(f"Manifest file not found: {manifest_path}")

    manifest = ManifestParser.load(manifest_path)

    if args.show or not args.validate:
        manifest.print_table()

    if args.validate:
        is_valid, errors = manifest.validate(strict=True)
        if not is_valid:
            logger.fail(f"Manifest validation failed with {len(errors)} missing file(s).")
        logger.success("Manifest is fully valid! All source files exist.")


if __name__ == "__main__":
    main()
