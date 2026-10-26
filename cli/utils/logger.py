#!/usr/bin/env python3
"""
OrangeUI Logging Utility
Provides rich colored console output and unified file logging:
Format: [YYYY-MM-DD HH:MM:SS] [LEVEL] [MODULE] Message
"""

import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

# Initialize consoles
console = Console()
console_err = Console(stderr=True)

class OrangeLogger:
    def __init__(self, module_name: str, log_dir: Optional[str] = None):
        self.module_name = module_name
        self.log_dir = Path(log_dir) if log_dir else self._find_log_dir()
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # Log file naming: YYYY-MM-DD_HH-MM.log
        now = datetime.now()
        log_filename = now.strftime("%Y-%m-%d_%H-%M") + ".log"
        self.log_file = self.log_dir / log_filename

    def _find_log_dir(self) -> Path:
        # Check current working directory or traverse upward to find repo root
        current = Path.cwd()
        for parent in [current] + list(current.parents):
            if (parent / "releases").is_dir() or (parent / "cli").is_dir():
                return parent / "releases" / "logs"
        return current / "releases" / "logs"

    def _write_file(self, level: str, message: str) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_line = f"[{timestamp}] [{level:<5}] [{self.module_name}] {message}\n"
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(log_line)
        except Exception as e:
            console_err.print(f"[bold red]Warning: Could not write to log file {self.log_file}: {e}[/bold red]")

    def info(self, message: str) -> None:
        self._write_file("INFO", message)
        console.print(f"[cyan][INFO][/cyan] [{self.module_name}] {message}")

    def success(self, message: str) -> None:
        self._write_file("INFO", f"SUCCESS: {message}")
        console.print(f"[bold green][SUCCESS][/bold green] [{self.module_name}] {message}")

    def warning(self, message: str) -> None:
        self._write_file("WARN", message)
        console.print(f"[bold yellow][WARNING][/bold yellow] [{self.module_name}] {message}")

    def error(self, message: str) -> None:
        self._write_file("ERROR", message)
        console_err.print(f"[bold red][ERROR][/bold red] [{self.module_name}] {message}")

    def debug(self, message: str) -> None:
        self._write_file("DEBUG", message)
        if os.environ.get("ORANGE_DEBUG") == "1":
            console.print(f"[dim][DEBUG] [{self.module_name}] {message}[/dim]")

    def step(self, step_num: int, total_steps: int, title: str) -> None:
        msg = f"Step {step_num}/{total_steps}: {title}"
        self._write_file("STEP", msg)
        console.rule(f"[bold magenta]{msg}[/bold magenta]")

    def rule(self, title: str) -> None:
        self._write_file("RULE", title)
        console.rule(f"[bold cyan]{title}[/bold cyan]")

    def fail(self, message: str, code: int = 1) -> None:
        """Fail-fast error handler."""
        self.error(message)
        console_err.print(f"[bold red]FATAL: Execution halted due to error.[/bold red]")
        sys.exit(code)

    def banner(self, title: str, subtitle: Optional[str] = None) -> None:
        content = f"[bold yellow]{title}[/bold yellow]"
        if subtitle:
            content += f"\n[dim]{subtitle}[/dim]"
        console.print(Panel(content, border_style="orange3", expand=False))


def get_logger(module_name: str, log_dir: Optional[str] = None) -> OrangeLogger:
    return OrangeLogger(module_name=module_name, log_dir=log_dir)
