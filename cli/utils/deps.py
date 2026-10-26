#!/usr/bin/env python3
"""
OrangeUI Dependency Checker
Validates host utilities for Android ROM manipulation.
"""

import shutil
import sys
from typing import Dict, List, Optional, Tuple

from rich.console import Console
from rich.table import Table

console = Console()

TOOLCHAIN_SPEC = {
    # Tool: (Required or Optional, Purpose)
    "lpunpack": (True, "Unpack logical partitions from super.img"),
    "lpmake": (True, "Create Android dynamic partition super.img"),
    "lpdump": (False, "Dump dynamic partition metadata from super.img"),
    "simg2img": (False, "Convert Android sparse images to raw images"),
    "img2simg": (False, "Convert raw images to Android sparse format"),
    "e2fsdroid": (False, "Inject files and SElinux contexts into ext4 images"),
    "mke2fs": (False, "Format and build ext4 partition filesystem images"),
    "debugfs": (False, "Inspect and extract files from ext4 filesystem images"),
    "xz": (True, "Extract .xz archives for GSI downloads"),
    "unzip": (True, "Extract ZIP archives (payload, APKs, flashables)"),
    "apktool": (False, "Decompile and rebuild APKs for smali patching"),
    "jadx": (False, "Disassemble and decompile DEX bytecode to Java"),
    "baksmali": (False, "Disassemble DEX files to smali"),
    "smali": (False, "Assemble smali to DEX files"),
}


def check_command(name: str) -> Optional[str]:
    """Return path to executable if found, None otherwise."""
    return shutil.which(name)


def check_dependencies(tools: Optional[List[str]] = None) -> Dict[str, Tuple[bool, bool, str, Optional[str]]]:
    """
    Check availability of specified tools (or default toolchain).
    Returns dict: name -> (is_available, is_required, purpose, path)
    """
    target_tools = tools if tools is not None else list(TOOLCHAIN_SPEC.keys())
    results = {}
    for tool in target_tools:
        is_req, purpose = TOOLCHAIN_SPEC.get(tool, (False, "Auxiliary utility"))
        path = check_command(tool)
        results[tool] = (path is not None, is_req, purpose, path)
    return results


def print_dependency_table(tools: Optional[List[str]] = None) -> bool:
    """
    Print rich table of dependencies.
    Returns True if all required tools are satisfied, False otherwise.
    """
    results = check_dependencies(tools)
    table = Table(title="OrangeUI Toolchain & Dependencies", border_style="cyan")
    table.add_column("Tool", style="bold white")
    table.add_column("Status", justify="center")
    table.add_column("Type", justify="center")
    table.add_column("Path / Note", style="dim")
    table.add_column("Purpose", style="italic")

    all_required_met = True

    for tool, (avail, req, purpose, path) in results.items():
        type_str = "[bold red]Required[/bold red]" if req else "[dim]Optional[/dim]"
        if avail:
            status_str = "[bold green]✓ OK[/bold green]"
            path_str = path or ""
        else:
            if req:
                status_str = "[bold red]✗ MISSING[/bold red]"
                all_required_met = False
            else:
                status_str = "[yellow]! NOT FOUND[/yellow]"
            path_str = "Not installed in PATH"

        table.add_row(tool, status_str, type_str, path_str, purpose)

    console.print(table)
    return all_required_met


def require_tool(tool: str, logger=None) -> str:
    """Ensure tool is present or fail immediately."""
    path = check_command(tool)
    if not path:
        msg = f"Required tool '{tool}' is not installed or not in PATH."
        if logger:
            logger.fail(msg)
        else:
            console.print(f"[bold red]FATAL: {msg}[/bold red]", file=sys.stderr)
            sys.exit(1)
    return path


if __name__ == "__main__":
    ok = print_dependency_table()
    sys.exit(0 if ok else 1)
