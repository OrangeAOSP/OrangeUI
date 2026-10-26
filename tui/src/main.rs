use std::io::{self, BufRead, BufReader};
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::sync::mpsc::{channel, Receiver, Sender};
use std::thread;
use std::time::Duration;

use chrono::Local;
use crossterm::{
    event::{self, Event, KeyCode, KeyEventKind},
    execute,
    terminal::{disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen},
};
use ratatui::{
    backend::CrosstermBackend,
    layout::{Constraint, Direction, Layout},
    style::{Color, Modifier, Style},
    text::{Line, Span},
    widgets::{Block, Borders, List, ListItem, ListState, Paragraph, Wrap},
    Frame, Terminal,
};

#[derive(Clone)]
struct MenuItem {
    index: usize,
    title: &'static str,
    description: &'static str,
    script_rel: &'static str,
    default_args: &'static [&'static str],
}

const MENU_ITEMS: &[MenuItem] = &[
    MenuItem {
        index: 1,
        title: "Line: Full Pipeline Execution (--line)",
        description: "Run complete ROM modification chain: unpack, extract HyperOS, patch, build release",
        script_rel: "cli/pipeline.py",
        default_args: &["--line"],
    },
    MenuItem {
        index: 2,
        title: "Unpack super.img",
        description: "Extract system, vendor, product, system_ext, mi_ext partitions via lpunpack",
        script_rel: "cli/repack_super.py",
        default_args: &["unpack", "--input", "super.img", "--output", "extracted/super"],
    },
    MenuItem {
        index: 3,
        title: "Extract HyperOS Apps & Frameworks",
        description: "Discover and copy system applications, lib64 native libs, and framework jars",
        script_rel: "cli/extract_hyperos.py",
        default_args: &["--system", "extracted/charoite", "--output", "inject"],
    },
    MenuItem {
        index: 4,
        title: "Inject APKs & Frameworks",
        description: "Inject APKs, lib64, framework jars, build.prop.patch, and sepolicy into system",
        script_rel: "cli/inject_apks.py",
        default_args: &["--target", "extracted/super", "--inject", "inject"],
    },
    MenuItem {
        index: 5,
        title: "Repack super.img",
        description: "Build new flashable super.img using lpmake (sparse, dm-verity disabled)",
        script_rel: "cli/repack_super.py",
        default_args: &["repack", "--input", "extracted/super", "--output", "releases/super.img"],
    },
    MenuItem {
        index: 6,
        title: "Build OrangeUI for Charoite",
        description: "Redmi Note 15 Pro 4G pipeline: GSI repack, MTK fixes, fastboot flashable ZIP",
        script_rel: "cli/charoite_builder.py",
        default_args: &["--output", "releases/charoite"],
    },
    MenuItem {
        index: 7,
        title: "Clear Cache: RAW Images (--clear=raw)",
        description: "Remove temporary decompressed raw images (*_raw.img, super_unsparse.img)",
        script_rel: "cli/pipeline.py",
        default_args: &["--clear=raw"],
    },
    MenuItem {
        index: 8,
        title: "Clear Cache: Full (--clear=all)",
        description: "Purge all temporary caches, unpacked partition directories, and build artifacts",
        script_rel: "cli/pipeline.py",
        default_args: &["--clear=all"],
    },
    MenuItem {
        index: 9,
        title: "Clear Cache: Output Artifacts (--clear=out)",
        description: "Remove extracted APKs, JARs in inject/ and generated release packages",
        script_rel: "cli/pipeline.py",
        default_args: &["--clear=out"],
    },
    MenuItem {
        index: 10,
        title: "Compact: GZIP Outputs (--compact-gzip=out)",
        description: "Package output APKs and framework JARs into a compressed .tar.gz archive",
        script_rel: "cli/pipeline.py",
        default_args: &["--compact-gzip=out"],
    },
    MenuItem {
        index: 11,
        title: "Compact: XZ Maximum Compression (--compact-xz=out)",
        description: "Package output APKs and JARs into ultra-compressed .tar.xz (preset 9)",
        script_rel: "cli/pipeline.py",
        default_args: &["--compact-xz=out"],
    },
    MenuItem {
        index: 12,
        title: "Compact: TAR Uncompressed (--compact-tar=all)",
        description: "Package all workspace deliverables into an uncompressed .tar archive",
        script_rel: "cli/pipeline.py",
        default_args: &["--compact-tar=all"],
    },
    MenuItem {
        index: 13,
        title: "Patch Framework (Smali)",
        description: "Bypass signature verification in PMS and generate MIUI stub classes",
        script_rel: "cli/patch_framework.py",
        default_args: &["dir", "--path", "extracted/smali"],
    },
    MenuItem {
        index: 14,
        title: "Diagnostics & Manifest Validation",
        description: "Verify host toolchain dependencies and validate manifest.json strictly",
        script_rel: "cli/manifest_parser.py",
        default_args: &["--manifest", "inject/manifest.json", "--show"],
    },
    MenuItem {
        index: 15,
        title: "Exit",
        description: "Exit OrangeUI TUI shell",
        script_rel: "",
        default_args: &[],
    },
];

enum ProcessMessage {
    Line(bool, String), // is_stderr, text
    Finished(bool, i32), // is_success, exit_code
}

#[derive(PartialEq)]
enum TaskStatus {
    Idle,
    Running(String),
    Success(String),
    Failed(String, i32),
}

struct App {
    menu_state: ListState,
    log_lines: Vec<(Color, String)>,
    log_scroll: u16,
    auto_scroll: bool,
    status: TaskStatus,
    receiver: Option<Receiver<ProcessMessage>>,
    repo_root: PathBuf,
}

impl App {
    fn new(repo_root: PathBuf) -> Self {
        let mut menu_state = ListState::default();
        menu_state.select(Some(0));

        let mut app = Self {
            menu_state,
            log_lines: Vec::new(),
            log_scroll: 0,
            auto_scroll: true,
            status: TaskStatus::Idle,
            receiver: None,
            repo_root,
        };

        app.add_log(Color::Yellow, "🍊 Welcome to OrangeUI TUI Shell (Afterglow Edition)!");
        app.add_log(Color::DarkGray, "Ready for tasks. Use arrows or numbers to navigate and launch operations.");
        app
    }

    fn add_log(&mut self, color: Color, msg: &str) {
        let timestamp = Local::now().format("%H:%M:%S").to_string();
        self.log_lines.push((color, format!("[{timestamp}] {msg}")));
        if self.auto_scroll {
            let total = self.log_lines.len() as u16;
            if total > 20 {
                self.log_scroll = total - 20;
            }
        }
    }

    fn select_next(&mut self) {
        let current = self.menu_state.selected().unwrap_or(0);
        let next = if current + 1 >= MENU_ITEMS.len() { 0 } else { current + 1 };
        self.menu_state.select(Some(next));
    }

    fn select_prev(&mut self) {
        let current = self.menu_state.selected().unwrap_or(0);
        let prev = if current == 0 { MENU_ITEMS.len() - 1 } else { current - 1 };
        self.menu_state.select(Some(prev));
    }

    fn select_index(&mut self, idx: usize) {
        if idx < MENU_ITEMS.len() {
            self.menu_state.select(Some(idx));
        }
    }

    fn run_selected(&mut self) {
        let idx = self.menu_state.selected().unwrap_or(0);
        self.run_item_at(idx);
    }

    fn run_item_at(&mut self, idx: usize) {
        if idx >= MENU_ITEMS.len() {
            return;
        }

        let item = &MENU_ITEMS[idx];
        if item.script_rel.is_empty() {
            // Exit option handled by caller
            return;
        }

        if let TaskStatus::Running(ref name) = self.status {
            self.add_log(Color::Red, &format!("Task '{name}' is already running! Please wait for completion."));
            return;
        }

        let script_path = self.repo_root.join(item.script_rel);
        let args: Vec<String> = item.default_args.iter().map(|s| s.to_string()).collect();

        self.add_log(Color::Cyan, &format!("--- Launching Task: {} ---", item.title));
        self.add_log(Color::DarkGray, &format!("Command: python3 {} {}", item.script_rel, args.join(" ")));

        self.status = TaskStatus::Running(item.title.to_string());

        let (tx, rx): (Sender<ProcessMessage>, Receiver<ProcessMessage>) = channel();
        self.receiver = Some(rx);

        let cwd = self.repo_root.clone();

        thread::spawn(move || {
            let mut child = match Command::new("python3")
                .arg(&script_path)
                .args(&args)
                .current_dir(&cwd)
                .stdout(Stdio::piped())
                .stderr(Stdio::piped())
                .spawn()
            {
                Ok(c) => c,
                Err(e) => {
                    let _ = tx.send(ProcessMessage::Line(true, format!("Failed to spawn process: {e}")));
                    let _ = tx.send(ProcessMessage::Finished(false, 1));
                    return;
                }
            };

            let stdout = child.stdout.take();
            let stderr = child.stderr.take();

            let tx_out = tx.clone();
            if let Some(out) = stdout {
                thread::spawn(move || {
                    let reader = BufReader::new(out);
                    for line in reader.lines().flatten() {
                        if tx_out.send(ProcessMessage::Line(false, line)).is_err() {
                            break;
                        }
                    }
                });
            }

            let tx_err = tx.clone();
            if let Some(err) = stderr {
                thread::spawn(move || {
                    let reader = BufReader::new(err);
                    for line in reader.lines().flatten() {
                        if tx_err.send(ProcessMessage::Line(true, line)).is_err() {
                            break;
                        }
                    }
                });
            }

            let status = child.wait();
            match status {
                Ok(exit_status) => {
                    let code = exit_status.code().unwrap_or(-1);
                    let _ = tx.send(ProcessMessage::Finished(exit_status.success(), code));
                }
                Err(e) => {
                    let _ = tx.send(ProcessMessage::Line(true, format!("Error waiting for process: {e}")));
                    let _ = tx.send(ProcessMessage::Finished(false, 1));
                }
            }
        });
    }

    fn check_messages(&mut self) {
        let mut messages = Vec::new();
        if let Some(ref rx) = self.receiver {
            while let Ok(msg) = rx.try_recv() {
                messages.push(msg);
            }
        }

        let mut finished = None;
        for msg in messages {
            match msg {
                ProcessMessage::Line(is_stderr, text) => {
                    let color = if is_stderr { Color::Red } else { Color::White };
                    self.add_log(color, &text);
                }
                ProcessMessage::Finished(success, code) => {
                    finished = Some((success, code));
                }
            }
        }

        if let Some((success, code)) = finished {
            let current_name = match &self.status {
                TaskStatus::Running(n) => n.clone(),
                _ => "Task".to_string(),
            };

            if success {
                self.add_log(Color::Green, &format!("✓ {} completed successfully (exit code 0)", current_name));
                self.status = TaskStatus::Success(current_name);
            } else {
                self.add_log(Color::LightRed, &format!("✗ {} failed (exit code {})", current_name, code));
                self.status = TaskStatus::Failed(current_name, code);
            }
            self.receiver = None;
        }
    }
}

fn find_repo_root() -> PathBuf {
    let current = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
    for ancestor in current.ancestors() {
        if ancestor.join("cli").is_dir() && ancestor.join("inject").is_dir() {
            return ancestor.to_path_buf();
        }
    }
    current
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<String> = std::env::args().collect();
    let repo_root = find_repo_root();

    // If CLI flags were passed directly to TUI binary (--line, --clear=..., --compact-gzip=..., etc.)
    if args.len() > 1 {
        let pipeline_script = repo_root.join("cli/pipeline.py");
        let mut cmd = Command::new("python3");
        cmd.arg(&pipeline_script);
        for a in args.iter().skip(1) {
            cmd.arg(a);
        }
        cmd.current_dir(&repo_root);
        let status = cmd.status()?;
        std::process::exit(status.code().unwrap_or(0));
    }

    enable_raw_mode()?;
    let mut stdout = io::stdout();
    execute!(stdout, EnterAlternateScreen)?;
    let backend = CrosstermBackend::new(stdout);
    let mut terminal = Terminal::new(backend)?;

    let mut app = App::new(repo_root);

    let tick_rate = Duration::from_millis(50);
    let mut should_exit = false;

    while !should_exit {
        app.check_messages();

        terminal.draw(|f| ui(f, &mut app))?;

        if event::poll(tick_rate)? {
            if let Event::Key(key) = event::read()? {
                if key.kind == KeyEventKind::Press {
                    match key.code {
                        KeyCode::Char('q') | KeyCode::Esc => {
                            should_exit = true;
                        }
                        KeyCode::Char('c') => {
                            app.log_lines.clear();
                            app.log_scroll = 0;
                            app.add_log(Color::DarkGray, "Log buffer cleared.");
                        }
                        KeyCode::Up => {
                            app.select_prev();
                        }
                        KeyCode::Down => {
                            app.select_next();
                        }
                        KeyCode::PageUp => {
                            if app.log_scroll > 5 {
                                app.log_scroll -= 5;
                            } else {
                                app.log_scroll = 0;
                            }
                            app.auto_scroll = false;
                        }
                        KeyCode::PageDown => {
                            let max_scroll = app.log_lines.len().saturating_sub(10) as u16;
                            if app.log_scroll + 5 < max_scroll {
                                app.log_scroll += 5;
                            } else {
                                app.log_scroll = max_scroll;
                                app.auto_scroll = true;
                            }
                        }
                        KeyCode::Enter => {
                            let selected = app.menu_state.selected().unwrap_or(0);
                            if selected == MENU_ITEMS.len() - 1 {
                                should_exit = true;
                            } else {
                                app.run_selected();
                            }
                        }
                        KeyCode::Char(c) if c.is_ascii_digit() => {
                            if let Some(digit) = c.to_digit(10) {
                                if digit >= 1 && (digit as usize) <= MENU_ITEMS.len() {
                                    let idx = (digit - 1) as usize;
                                    app.select_index(idx);
                                    if idx == MENU_ITEMS.len() - 1 {
                                        should_exit = true;
                                    } else {
                                        app.run_item_at(idx);
                                    }
                                }
                            }
                        }
                        _ => {}
                    }
                }
            }
        }
    }

    disable_raw_mode()?;
    execute!(terminal.backend_mut(), LeaveAlternateScreen)?;
    terminal.show_cursor()?;

    Ok(())
}

fn ui(f: &mut Frame, app: &mut App) {
    let size = f.area();

    // Vertical layout: Header, Body, Footer
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(3), // Header
            Constraint::Min(10),   // Main Body (Menu + Logs)
            Constraint::Length(3), // Footer
        ])
        .split(size);

    // 1. Header with dynamic status badge
    let status_span = match &app.status {
        TaskStatus::Idle => Span::styled(" [READY] ", Style::default().fg(Color::Black).bg(Color::Cyan)),
        TaskStatus::Running(task) => Span::styled(
            format!(" [RUNNING: {task}] "),
            Style::default().fg(Color::Black).bg(Color::Yellow).add_modifier(Modifier::BOLD),
        ),
        TaskStatus::Success(task) => Span::styled(
            format!(" [SUCCESS: {task}] "),
            Style::default().fg(Color::Black).bg(Color::Green).add_modifier(Modifier::BOLD),
        ),
        TaskStatus::Failed(task, code) => Span::styled(
            format!(" [FAILED: {task} ({code})] "),
            Style::default().fg(Color::White).bg(Color::Red).add_modifier(Modifier::BOLD),
        ),
    };

    let header_line = Line::from(vec![
        Span::styled("🍊 OrangeUI Toolkit ", Style::default().fg(Color::Rgb(255, 140, 0)).add_modifier(Modifier::BOLD)),
        Span::raw("— Custom ROM & GSI Builder (Afterglow Edition)  "),
        status_span,
    ]);

    let header_block = Block::default()
        .borders(Borders::ALL)
        .border_style(Style::default().fg(Color::Rgb(255, 140, 0)));
    let header_para = Paragraph::new(header_line).block(header_block);
    f.render_widget(header_para, chunks[0]);

    // 2. Main Body Split: Left (Menu & Details), Right (Log Window)
    let body_chunks = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([
            Constraint::Percentage(44), // Left: Menu
            Constraint::Percentage(56), // Right: Logs
        ])
        .split(chunks[1]);

    // Left Column: Menu Items + Description Box
    let left_chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Min(9),
            Constraint::Length(6),
        ])
        .split(body_chunks[0]);

    let menu_items: Vec<ListItem> = MENU_ITEMS
        .iter()
        .map(|item| {
            ListItem::new(Line::from(vec![
                Span::styled(format!("[{:>2}] ", item.index), Style::default().fg(Color::Yellow).add_modifier(Modifier::BOLD)),
                Span::raw(item.title),
            ]))
        })
        .collect();

    let menu_list = List::new(menu_items)
        .block(
            Block::default()
                .title(" Operations Menu ")
                .borders(Borders::ALL)
                .border_style(Style::default().fg(Color::Cyan)),
        )
        .highlight_style(
            Style::default()
                .bg(Color::Rgb(255, 140, 0))
                .fg(Color::Black)
                .add_modifier(Modifier::BOLD),
        )
        .highlight_symbol("▶ ");

    f.render_stateful_widget(menu_list, left_chunks[0], &mut app.menu_state);

    // Selected item detail box
    let selected_idx = app.menu_state.selected().unwrap_or(0);
    let selected_item = &MENU_ITEMS[selected_idx];
    let detail_text = vec![
        Line::from(vec![
            Span::styled("Description: ", Style::default().fg(Color::Yellow)),
            Span::raw(selected_item.description),
        ]),
        Line::from(vec![
            Span::styled("Script: ", Style::default().fg(Color::Cyan)),
            Span::raw(selected_item.script_rel),
        ]),
        Line::from(vec![
            Span::styled("Arguments: ", Style::default().fg(Color::Magenta)),
            Span::raw(selected_item.default_args.join(" ")),
        ]),
    ];

    let detail_block = Block::default()
        .title(" Task Details ")
        .borders(Borders::ALL)
        .border_style(Style::default().fg(Color::DarkGray));
    let detail_para = Paragraph::new(detail_text).block(detail_block).wrap(Wrap { trim: true });
    f.render_widget(detail_para, left_chunks[1]);

    // Right Column: Live Log Console
    let log_title = format!(" Output Console ({}) ", app.log_lines.len());
    let log_block = Block::default()
        .title(log_title)
        .borders(Borders::ALL)
        .border_style(Style::default().fg(Color::Green));

    let log_display: Vec<Line> = app
        .log_lines
        .iter()
        .map(|(color, text)| Line::from(vec![Span::styled(text.clone(), Style::default().fg(*color))]))
        .collect();

    let log_para = Paragraph::new(log_display)
        .block(log_block)
        .scroll((app.log_scroll, 0))
        .wrap(Wrap { trim: false });

    f.render_widget(log_para, body_chunks[1]);

    // 3. Footer: Navigation hotkeys
    let footer_text = Line::from(vec![
        Span::styled("[↑/↓] ", Style::default().fg(Color::Yellow).add_modifier(Modifier::BOLD)),
        Span::raw("Navigate  "),
        Span::styled("[Enter] ", Style::default().fg(Color::Yellow).add_modifier(Modifier::BOLD)),
        Span::raw("Launch  "),
        Span::styled("[PgUp/PgDn] ", Style::default().fg(Color::Yellow).add_modifier(Modifier::BOLD)),
        Span::raw("Scroll  "),
        Span::styled("[C] ", Style::default().fg(Color::Yellow).add_modifier(Modifier::BOLD)),
        Span::raw("Clear  "),
        Span::styled("[Q / Esc] ", Style::default().fg(Color::Yellow).add_modifier(Modifier::BOLD)),
        Span::raw("Exit"),
    ]);

    let footer_block = Block::default()
        .borders(Borders::ALL)
        .border_style(Style::default().fg(Color::DarkGray));
    let footer_para = Paragraph::new(footer_text).block(footer_block);
    f.render_widget(footer_para, chunks[2]);
}
