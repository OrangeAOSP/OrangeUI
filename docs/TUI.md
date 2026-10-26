# 🖥️ OrangeUI TUI Manual (Afterglow Edition)

Terminal User Interface (TUI) for the OrangeUI ROM & GSI Customization Toolkit.

Written in **Rust** using `ratatui` (v0.30) and `crossterm` (v0.29).

---

## 1. Compilation & Launch

### 1.1. Build from Source
Requires Rust 1.80+ and Cargo:
```bash
cd tui
cargo build --release
```
The binary will be compiled to `tui/target/release/orangeui-tui`.

### 1.2. Launching TUI
From the root of the OrangeUI workspace:
```bash
./tui/target/release/orangeui-tui
```

### 1.3. Direct CLI Mode via TUI Binary
The compiled Rust binary can also be invoked directly with CLI flags:
```bash
./tui/target/release/orangeui-tui --line
./tui/target/release/orangeui-tui --clear=all
./tui/target/release/orangeui-tui --compact-gzip=out
```

---

## 2. Layout & Interface Architecture

The TUI is structured into three primary panels:

1. **Header:**
   - Title: `🍊 OrangeUI Toolkit — Custom ROM & GSI Builder (Afterglow Edition)`
   - Status Badge:
     - `[READY]` — system idle.
     - `[RUNNING: <Task>]` (yellow) — Python background process executing.
     - `[SUCCESS: <Task>]` (green) — task completed with exit code 0.
     - `[FAILED: <Task> (code)]` (red) — process terminated with error.

2. **Main Workspace:**
   - **Left Panel (Operations Menu + Task Details):**
     - Operations list with numeric indices.
     - Task detail card displaying script path, description, and CLI arguments.
   - **Right Panel (Real-Time Output Console):**
     - Colored live stream of `stdout` (white) and `stderr` (red).
     - Automatic scrolling to the latest output.

3. **Footer:**
   - Navigation hotkey hints.

---

## 3. Operations Menu

| Index | Operation Title | Executed Command |
|---|---|---|
| `[ 1]` | **Line: Full Pipeline Execution** | `python3 cli/pipeline.py --line` |
| `[ 2]` | **Unpack super.img** | `python3 cli/repack_super.py unpack --input super.img --output extracted/super` |
| `[ 3]` | **Extract HyperOS Apps & Frameworks** | `python3 cli/extract_hyperos.py --system extracted/charoite --output inject` |
| `[ 4]` | **Inject APKs & Frameworks** | `python3 cli/inject_apks.py --target extracted/super --inject inject` |
| `[ 5]` | **Repack super.img** | `python3 cli/repack_super.py repack --input extracted/super --output releases/super.img` |
| `[ 6]` | **Build OrangeUI for Charoite** | `python3 cli/charoite_builder.py --output releases/charoite` |
| `[ 7]` | **Clear Cache: RAW Images** | `python3 cli/pipeline.py --clear=raw` |
| `[ 8]` | **Clear Cache: Full Purge** | `python3 cli/pipeline.py --clear=all` |
| `[ 9]` | **Clear Cache: Output Artifacts** | `python3 cli/pipeline.py --clear=out` |
| `[10]` | **Compact: GZIP Output Files** | `python3 cli/pipeline.py --compact-gzip=out` |
| `[11]` | **Compact: XZ Maximum Compression** | `python3 cli/pipeline.py --compact-xz=out` |
| `[12]` | **Compact: TAR Uncompressed** | `python3 cli/pipeline.py --compact-tar=all` |
| `[13]` | **Patch Framework (Smali)** | `python3 cli/patch_framework.py dir --path extracted/smali` |
| `[14]` | **Diagnostics & Manifest** | `python3 cli/manifest_parser.py --manifest inject/manifest.json --show` |
| `[15]` | **Exit** | Terminate OrangeUI TUI |

---

## 4. Keybindings

- `↑` / `↓` — Navigate menu items.
- `Enter` — Launch selected operation.
- `1` .. `9` — Quick launch corresponding operation by number.
- `PageUp` / `PageDown` — Scroll log history up and down.
- `C` — Clear log output buffer.
- `Q` or `Esc` — Exit TUI.
