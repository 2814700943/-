import ctypes
import ctypes.wintypes
import json
import os
import queue
import shutil
import smtplib
import ssl
import subprocess
import sys
import threading
import time
import zipfile
from dataclasses import dataclass, asdict
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
import tkinter as tk
from tkinter import BooleanVar, StringVar, Tk, filedialog, messagebox, ttk

import customtkinter as ctk
from PIL import Image, ImageGrab


APP_NAME = "谁动了我的电脑"
APP_VERSION = "v2.3.1"
AUTHOR_NAME = "by-装纯研习社"
CONTACT_TEXT = "微信号 BAIY_13"
WECHAT_ID = "BAIY_13"
AD_SITE = "www.zcyai.cn"
AD_TEXT = f"超低价 GPT PULS 会员 已绑定手机号 可登 Codex 谷歌会员 一年 联系作者 {AD_SITE}"
BASE_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
DEFAULT_OUTPUT_DIR = BASE_DIR / "captures"
LOG_DIR = BASE_DIR / "logs"
LRESULT = getattr(ctypes.wintypes, "LRESULT", ctypes.wintypes.LPARAM)


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def ensure_dirs(*paths: Path) -> None:
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)


@dataclass
class AppConfig:
    output_dir: str = str(DEFAULT_OUTPUT_DIR)
    image_format: str = "jpg"
    immediate_guard_trigger: bool = True
    idle_seconds_before_guard_trigger: int = 30
    screenshot_interval_seconds: int = 60
    camera_interval_seconds: int = 300
    storage_limit_mb: int = 500
    save_screenshots: bool = True
    save_camera_images: bool = True
    show_warning_before_lock: bool = True
    output_target: str = "local"
    email_realtime: bool = False
    email_batch_minutes: int = 5
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    mail_from: str = ""
    mail_to: str = ""
    encrypt_local_zip: bool = False
    zip_password_hint: str = "请使用系统账户权限保护此目录；标准 zip 加密需第三方库。"
    shortcut_guard_mode: str = "Ctrl+1"
    shortcut_record_mode: str = "Ctrl+2"
    shortcut_stop: str = "Esc"
    shortcut_save: str = "Ctrl+S"
    shortcut_open_dir: str = "Ctrl+O"
    shortcut_export_logs: str = "Ctrl+E"
    shortcut_refresh: str = "F5"

    @classmethod
    def load(cls) -> "AppConfig":
        if not CONFIG_PATH.exists():
            cfg = cls()
            cfg.save()
            return cfg
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        merged = asdict(cls())
        merged.update(data)
        return cls(**merged)

    def save(self) -> None:
        CONFIG_PATH.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


class ActivityLog:
    def __init__(self) -> None:
        ensure_dirs(LOG_DIR)
        self.path = LOG_DIR / f"activity_{now_stamp()}.jsonl"
        self.lock = threading.Lock()

    def write(self, event_type: str, detail: dict | None = None) -> None:
        payload = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "event": event_type,
            "detail": detail or {},
        }
        with self.lock:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


class Mailer:
    def __init__(self, cfg: AppConfig, log: ActivityLog) -> None:
        self.cfg = cfg
        self.log = log

    def enabled(self) -> bool:
        return (
            self.cfg.output_target == "email"
            and self.cfg.smtp_host
            and self.cfg.smtp_user
            and self.cfg.smtp_password
            and self.cfg.mail_to
        )

    def send_files(self, subject: str, body: str, files: list[Path]) -> None:
        if not self.enabled():
            self.log.write("email_skipped", {"reason": "SMTP 未配置完整"})
            return

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.cfg.mail_from or self.cfg.smtp_user
        msg["To"] = self.cfg.mail_to
        msg.set_content(body)

        for path in files:
            if not path.exists():
                continue
            maintype, subtype = "application", "octet-stream"
            suffix = path.suffix.lower()
            if suffix in {".jpg", ".jpeg"}:
                maintype, subtype = "image", "jpeg"
            elif suffix == ".png":
                maintype, subtype = "image", "png"
            elif suffix == ".txt":
                maintype, subtype = "text", "plain"
            with path.open("rb") as fh:
                msg.add_attachment(
                    fh.read(),
                    maintype=maintype,
                    subtype=subtype,
                    filename=path.name,
                )

        context = ssl.create_default_context()
        with smtplib.SMTP(self.cfg.smtp_host, self.cfg.smtp_port, timeout=20) as smtp:
            smtp.starttls(context=context)
            smtp.login(self.cfg.smtp_user, self.cfg.smtp_password)
            smtp.send_message(msg)
        self.log.write("email_sent", {"files": [str(p) for p in files]})


class CaptureService:
    def __init__(self, cfg: AppConfig, log: ActivityLog) -> None:
        self.cfg = cfg
        self.log = log

    @property
    def output_dir(self) -> Path:
        path = Path(self.cfg.output_dir).expanduser()
        ensure_dirs(path)
        return path

    def screenshot(self, prefix: str = "screen") -> Path:
        suffix = self.cfg.image_format.lower()
        if suffix not in {"jpg", "jpeg", "png"}:
            suffix = "jpg"
        path = self.output_dir / f"{prefix}_{now_stamp()}.{suffix}"
        image = ImageGrab.grab()
        if suffix in {"jpg", "jpeg"}:
            image = image.convert("RGB")
            image.save(path, quality=90)
        else:
            image.save(path)
        self.log.write("screenshot_saved", {"path": str(path)})
        return path

    def camera_photo(self, prefix: str = "camera") -> Path | None:
        try:
            import cv2  # type: ignore
        except Exception as exc:
            self.log.write("camera_unavailable", {"reason": f"opencv-python 未安装: {exc}"})
            return None

        suffix = self.cfg.image_format.lower()
        if suffix not in {"jpg", "jpeg", "png"}:
            suffix = "jpg"
        path = self.output_dir / f"{prefix}_{now_stamp()}.{suffix}"
        camera = cv2.VideoCapture(0)
        try:
            ok, frame = camera.read()
            if not ok:
                self.log.write("camera_capture_failed", {"reason": "无法读取摄像头画面"})
                return None
            cv2.imwrite(str(path), frame)
            self.log.write("camera_saved", {"path": str(path)})
            return path
        finally:
            camera.release()


class WindowsHooks:
    WH_KEYBOARD_LL = 13
    WH_MOUSE_LL = 14
    WM_KEYDOWN = 0x0100
    WM_SYSKEYDOWN = 0x0104
    WM_LBUTTONDOWN = 0x0201
    WM_RBUTTONDOWN = 0x0204
    WM_MBUTTONDOWN = 0x0207
    WM_MOUSEMOVE = 0x0200

    def __init__(self, callback) -> None:
        self.callback = callback
        self.user32 = ctypes.windll.user32
        self.kernel32 = ctypes.windll.kernel32
        self.kernel32.GetModuleHandleW.argtypes = [ctypes.wintypes.LPCWSTR]
        self.kernel32.GetModuleHandleW.restype = ctypes.wintypes.HMODULE
        self.kernel32.GetCurrentThreadId.restype = ctypes.wintypes.DWORD
        self.thread: threading.Thread | None = None
        self.thread_id = 0
        self.running = threading.Event()
        self.keyboard_hook = None
        self.mouse_hook = None
        self._keyboard_proc = self._make_proc("keyboard")
        self._mouse_proc = self._make_proc("mouse")
        self._last_mouse_move = 0.0
        self.user32.SetWindowsHookExW.argtypes = [
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.wintypes.HINSTANCE,
            ctypes.wintypes.DWORD,
        ]
        self.user32.SetWindowsHookExW.restype = ctypes.wintypes.HHOOK
        self.user32.CallNextHookEx.argtypes = [
            ctypes.wintypes.HHOOK,
            ctypes.c_int,
            ctypes.wintypes.WPARAM,
            ctypes.wintypes.LPARAM,
        ]
        self.user32.CallNextHookEx.restype = LRESULT
        self.user32.UnhookWindowsHookEx.argtypes = [ctypes.wintypes.HHOOK]
        self.user32.PostThreadMessageW.argtypes = [
            ctypes.wintypes.DWORD,
            ctypes.wintypes.UINT,
            ctypes.wintypes.WPARAM,
            ctypes.wintypes.LPARAM,
        ]

    def _make_proc(self, kind: str):
        HOOKPROC = ctypes.WINFUNCTYPE(
            LRESULT,
            ctypes.c_int,
            ctypes.wintypes.WPARAM,
            ctypes.wintypes.LPARAM,
        )

        def proc(n_code, w_param, l_param):
            if n_code == 0:
                event = None
                if kind == "keyboard" and w_param in (self.WM_KEYDOWN, self.WM_SYSKEYDOWN):
                    event = "keyboard_activity"
                elif kind == "mouse":
                    if w_param in (self.WM_LBUTTONDOWN, self.WM_RBUTTONDOWN, self.WM_MBUTTONDOWN):
                        event = "mouse_click"
                    elif w_param == self.WM_MOUSEMOVE:
                        now = time.monotonic()
                        if now - self._last_mouse_move > 2.0:
                            self._last_mouse_move = now
                            event = "mouse_move"
                if event:
                    self.callback(event)
            return self.user32.CallNextHookEx(None, n_code, w_param, l_param)

        return HOOKPROC(proc)

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.running.set()
        self.thread = threading.Thread(target=self._run, name="WindowsHooks", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.running.clear()
        if self.keyboard_hook:
            self.user32.UnhookWindowsHookEx(self.keyboard_hook)
            self.keyboard_hook = None
        if self.mouse_hook:
            self.user32.UnhookWindowsHookEx(self.mouse_hook)
            self.mouse_hook = None
        if self.thread_id:
            self.user32.PostThreadMessageW(self.thread_id, 0x0012, 0, 0)

    def _run(self) -> None:
        self.thread_id = self.kernel32.GetCurrentThreadId()
        module = self.kernel32.GetModuleHandleW(None)
        self.keyboard_hook = self.user32.SetWindowsHookExW(
            self.WH_KEYBOARD_LL, self._keyboard_proc, module, 0
        )
        self.mouse_hook = self.user32.SetWindowsHookExW(
            self.WH_MOUSE_LL, self._mouse_proc, module, 0
        )
        msg = ctypes.wintypes.MSG()
        while self.running.is_set() and self.user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            self.user32.TranslateMessage(ctypes.byref(msg))
            self.user32.DispatchMessageW(ctypes.byref(msg))


def active_window_title() -> str:
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    length = user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def lock_workstation() -> bool:
    return bool(ctypes.windll.user32.LockWorkStation())


class MonitorApp:
    def __init__(self) -> None:
        self.cfg = AppConfig.load()
        ensure_dirs(Path(self.cfg.output_dir), LOG_DIR)
        self.log = ActivityLog()
        self.capture = CaptureService(self.cfg, self.log)
        self.mailer = Mailer(self.cfg, self.log)
        self.events: queue.Queue[str] = queue.Queue()
        self.mode = "idle"
        self.guard_triggered = False
        self.guard_grace_until = 0.0
        self.last_activity = time.monotonic()
        self.last_polled_mouse_event = 0.0
        self.last_cursor_pos = self.get_cursor_position()
        self.pressed_keys: set[int] = set()
        self.last_window_title = ""
        self.stop_recording = threading.Event()
        self.hooks = WindowsHooks(self.on_hook_event)

        self.root = ctk.CTk()
        self.root.title(f"{APP_NAME} {APP_VERSION}")
        self.root.geometry("1040x720")
        self.root.minsize(980, 680)
        self.root.overrideredirect(True)
        self.is_maximized = False
        self.normal_geometry = "1040x720"
        self.drag_start_x = 0
        self.drag_start_y = 0

        self.status_var = StringVar(value="未启动")
        self.output_dir_var = StringVar(value=self.cfg.output_dir)
        self.format_var = StringVar(value=self.cfg.image_format)
        self.immediate_guard_var = BooleanVar(value=self.cfg.immediate_guard_trigger)
        self.output_target_var = StringVar(value=self.cfg.output_target)
        self.idle_var = StringVar(value=str(self.cfg.idle_seconds_before_guard_trigger))
        self.screen_interval_var = StringVar(value=str(self.cfg.screenshot_interval_seconds))
        self.camera_interval_var = StringVar(value=str(self.cfg.camera_interval_seconds))
        self.storage_limit_var = StringVar(value=str(self.cfg.storage_limit_mb))
        self.warning_var = BooleanVar(value=self.cfg.show_warning_before_lock)
        self.email_realtime_var = BooleanVar(value=self.cfg.email_realtime)
        self.smtp_host_var = StringVar(value=self.cfg.smtp_host)
        self.smtp_port_var = StringVar(value=str(self.cfg.smtp_port))
        self.smtp_user_var = StringVar(value=self.cfg.smtp_user)
        self.smtp_password_var = StringVar(value=self.cfg.smtp_password)
        self.mail_to_var = StringVar(value=self.cfg.mail_to)
        self.shortcut_guard_var = StringVar(value=self.cfg.shortcut_guard_mode)
        self.shortcut_record_var = StringVar(value=self.cfg.shortcut_record_mode)
        self.shortcut_stop_var = StringVar(value=self.cfg.shortcut_stop)
        self.shortcut_save_var = StringVar(value=self.cfg.shortcut_save)
        self.shortcut_open_var = StringVar(value=self.cfg.shortcut_open_dir)
        self.shortcut_export_var = StringVar(value=self.cfg.shortcut_export_logs)
        self.shortcut_refresh_var = StringVar(value=self.cfg.shortcut_refresh)
        self.nav_buttons: dict[str, tk.Button] = {}
        self.pages: dict[str, tk.Frame] = {}
        self.content_frame: tk.Frame | None = None
        self.log_text = None
        self.log_tables: list[ttk.Treeview] = []
        self.recent_list_frames: list[tuple[ctk.CTkFrame, int, str]] = []
        self.recent_rows: list[dict] = []
        self.preview_images: list[ctk.CTkImage] = []
        self.shortcut_bindings: list[str] = []
        self.record_count_var = StringVar(value="0")
        self.last_run_var = StringVar(value="从未运行")
        self.output_summary_var = StringVar(value=self.compact_path(self.cfg.output_dir, 34))
        self.mail_summary_var = StringVar(value=self.cfg.mail_to or "未配置")
        self.active_nav_key = "home"

        self._build_ui()
        self.bind_shortcuts()
        self.root.after(250, self.process_events)
        self.root.after(250, self.poll_input_state)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _build_ui(self) -> None:
        self._build_ctk_ui()
        return

    def _build_ctk_ui(self) -> None:
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        root = self.root
        root.configure(fg_color="#06111f")

        shell = ctk.CTkFrame(root, fg_color="#071522", corner_radius=18, border_width=1, border_color="#1c344a")
        shell.pack(fill="both", expand=True, padx=0, pady=0)

        top = ctk.CTkFrame(shell, fg_color="transparent", height=50)
        top.pack(fill="x", padx=18, pady=(6, 0))
        top.pack_propagate(False)
        top.bind("<ButtonPress-1>", self.start_window_drag)
        top.bind("<B1-Motion>", self.drag_window)
        top.bind("<Double-Button-1>", lambda _event: self.toggle_maximize())

        ctk.CTkLabel(top, text="🛡", font=("Segoe UI Emoji", 22), text_color="#3a92ff").pack(side="left")
        ctk.CTkLabel(top, text=APP_NAME, font=("Microsoft YaHei UI", 16, "bold"), text_color="#f5f9ff").pack(side="left", padx=(8, 10))
        ctk.CTkLabel(top, text=APP_VERSION, font=("Segoe UI", 11), text_color="#8192a8").pack(side="left")

        for text, cmd, width in [
            ("⚙ 设置", lambda: self.show_page("settings"), 78),
            ("ⓘ 关于", lambda: self.show_page("help"), 78),
            ("─", self.minimize_window, 40),
            ("□", self.toggle_maximize, 40),
            ("×", self.close, 40),
        ]:
            ctk.CTkButton(
                top,
                text=text,
                command=cmd,
                width=width,
                height=32,
                fg_color="transparent",
                hover_color="#152b3f",
                text_color="#e8f1fb",
                corner_radius=8,
                font=("Microsoft YaHei UI", 12),
            ).pack(side="right", padx=(4, 0))

        body = ctk.CTkFrame(shell, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        sidebar = ctk.CTkFrame(body, fg_color="#101f2d", corner_radius=10, border_width=1, border_color="#21384e", width=218)
        sidebar.pack(side="left", fill="y", padx=(0, 0))
        sidebar.pack_propagate(False)

        ctk.CTkLabel(sidebar, text="🕵️", font=("Segoe UI Emoji", 50), text_color="#348cff").pack(pady=(24, 8))
        ctk.CTkLabel(sidebar, text=APP_NAME, font=("Microsoft YaHei UI", 18, "bold"), text_color="#ffffff").pack()
        ctk.CTkLabel(sidebar, text="保护隐私，守护安全", font=("Microsoft YaHei UI", 12), text_color="#8da0b7").pack(pady=(6, 18))

        ctk.CTkFrame(sidebar, fg_color="#263b51", height=1).pack(fill="x", padx=28, pady=(0, 14))

        nav = ctk.CTkFrame(sidebar, fg_color="transparent")
        nav.pack(fill="x", padx=14)
        for key, icon, label in [
            ("home", "⌂", "首页"),
            ("records", "☷", "记录查看"),
            ("settings", "⚙", "设置中心"),
            ("mail", "✉", "邮箱设置"),
            ("help", "?", "帮助文档"),
        ]:
            row = ctk.CTkFrame(nav, height=42, corner_radius=8, fg_color="transparent")
            row.pack(fill="x", pady=4)
            row.pack_propagate(False)
            row.nav_key = key  # type: ignore[attr-defined]
            icon_label = ctk.CTkLabel(row, text=icon, width=34, anchor="center", font=("Microsoft YaHei UI", 15), text_color="#d7e4f3")
            icon_label.pack(side="left", padx=(8, 4))
            text_label = ctk.CTkLabel(row, text=label, anchor="w", font=("Microsoft YaHei UI", 13), text_color="#d7e4f3")
            text_label.pack(side="left", fill="x", expand=True)
            row.nav_children = (icon_label, text_label)  # type: ignore[attr-defined]
            for widget in (row, icon_label, text_label):
                widget.bind("<Button-1>", lambda _event, page=key: self.show_page(page))
                widget.bind("<Enter>", lambda _event, item=row: item.configure(fg_color="#173452" if self.active_nav_key != item.nav_key else "#153b66"))
                widget.bind("<Leave>", lambda _event, item=row: item.configure(fg_color="#153b66" if self.active_nav_key == item.nav_key else "transparent"))
            self.nav_buttons[key] = row

        status_card = ctk.CTkFrame(sidebar, fg_color="#162b3e", corner_radius=8, border_width=1, border_color="#244158")
        status_card.pack(side="bottom", fill="x", padx=12, pady=12)
        ctk.CTkLabel(status_card, text="🛡  保护可用", font=("Microsoft YaHei UI", 13, "bold"), text_color="#35d778").pack(anchor="w", padx=14, pady=(10, 2))
        ctk.CTkLabel(status_card, textvariable=self.last_run_var, font=("Microsoft YaHei UI", 10), text_color="#95a8bd").pack(anchor="w", padx=14)
        contact_label = ctk.CTkLabel(status_card, text=f"{CONTACT_TEXT}  点击复制", font=("Microsoft YaHei UI", 10), text_color="#7fb2ff", cursor="hand2")
        contact_label.pack(anchor="w", padx=14, pady=(2, 4))
        contact_label.bind("<Button-1>", lambda _event: self.copy_wechat())
        ad_label = ctk.CTkLabel(status_card, text=f"会员/服务咨询 {AD_SITE}", font=("Microsoft YaHei UI", 10), text_color="#ffbf6e", cursor="hand2")
        ad_label.pack(anchor="w", padx=14, pady=(0, 10))
        ad_label.bind("<Button-1>", lambda _event: self.copy_wechat())

        self.content_frame = ctk.CTkFrame(body, fg_color="#081725", corner_radius=10, border_width=1, border_color="#20384f")
        self.content_frame.pack(side="left", fill="both", expand=True)

        self.pages["home"] = self.ctk_home_page()
        self.pages["records"] = self.ctk_records_page()
        self.pages["settings"] = self.ctk_settings_page()
        self.pages["mail"] = self.ctk_mail_page()
        self.pages["help"] = self.ctk_help_page()
        self.show_page("home")

    def ctk_page(self) -> ctk.CTkFrame:
        page = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        page.place(relx=0, rely=0, relwidth=1, relheight=1)
        return page

    def compact_path(self, value: str, max_chars: int = 34) -> str:
        text = str(value)
        if len(text) <= max_chars:
            return text
        tail = text[-(max_chars - 3):]
        return f"...{tail}"

    def ctk_title(self, parent, title: str, subtitle: str) -> None:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=24, pady=(18, 2))
        ctk.CTkLabel(row, text="🛡", font=("Segoe UI Emoji", 17), text_color="#3391ff").pack(side="left", padx=(0, 8))
        ctk.CTkLabel(row, text=title, font=("Microsoft YaHei UI", 17, "bold"), text_color="#ffffff").pack(side="left")
        ctk.CTkLabel(parent, text=subtitle, font=("Microsoft YaHei UI", 11), text_color="#8498ae").pack(anchor="w", padx=24, pady=(0, 12))

    def ctk_home_page(self) -> ctk.CTkFrame:
        page = self.ctk_page()
        self.ctk_title(page, "选择监控模式", "请选择一种监控模式，保护您的电脑安全")

        cards = ctk.CTkFrame(page, fg_color="transparent")
        cards.pack(fill="x", padx=24)
        self.ctk_mode_card(cards, "🔒", "模式一：动了就锁屏拍照", "检测到操作后取证并锁屏", ["键鼠触发", "拍照/截图", "邮箱/本地"], "#123050", "#2f8cff", self.start_guard_mode).pack(side="left", fill="both", expand=True, padx=(0, 10))
        self.ctk_mode_card(cards, "📷", "模式二：持续监控记录", "定时截图、拍照并记录行为", ["定时采集", "窗口记录", "日志导出"], "#0e3b2e", "#36ca7a", self.start_record_mode).pack(side="left", fill="both", expand=True, padx=(10, 0))

        overview = ctk.CTkFrame(page, fg_color="transparent")
        overview.pack(fill="x", padx=24, pady=(12, 10))
        for title, detail, color in [
            ("键鼠检测", "Hook + 轮询兜底", "#2f8cff"),
            ("自动锁屏", "LockWorkStation", "#7aa7ff"),
            ("摄像头", "OpenCV 拍照", "#36ca7a"),
            ("截图", "Pillow ImageGrab", "#ffd36e"),
            ("邮件", "SMTP 附件发送", "#b48cff"),
            ("隐私", "不记录具体按键", "#ff8f70"),
        ]:
            self.info_chip(overview, title, detail, color).pack(side="left", fill="x", expand=True, padx=(0, 8))

        data = ctk.CTkFrame(page, fg_color="#101f2d", corner_radius=10, border_width=1, border_color="#1e3449")
        data.pack(fill="x", padx=24, pady=(0, 12))
        data.grid_columnconfigure((0, 1, 2), weight=1, uniform="data")

        left = ctk.CTkFrame(data, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=14, pady=12)
        ctk.CTkLabel(left, text="数据处理方式", font=("Microsoft YaHei UI", 12, "bold"), text_color="#ffffff").pack(anchor="w")
        ctk.CTkRadioButton(left, text="发送到邮箱", variable=self.output_target_var, value="email", command=self.save_config, text_color="#d7e4f3").pack(anchor="w", pady=(8, 2))
        ctk.CTkRadioButton(left, text="保存到本地", variable=self.output_target_var, value="local", command=self.save_config, text_color="#d7e4f3").pack(anchor="w", pady=(8, 0))

        mid = ctk.CTkFrame(data, fg_color="#0d1b28", corner_radius=0)
        mid.grid(row=0, column=1, sticky="nsew", padx=8, pady=12)
        ctk.CTkLabel(mid, text="✉", font=("Segoe UI Emoji", 30), text_color="#d7e8ff").pack(side="left", padx=(18, 12), pady=12)
        mid_text = ctk.CTkFrame(mid, fg_color="transparent")
        mid_text.pack(side="left", fill="both", expand=True, pady=12)
        ctk.CTkLabel(mid_text, text="当前邮箱", text_color="#8ba0b8").pack(anchor="w")
        ctk.CTkLabel(mid_text, textvariable=self.mail_summary_var, text_color="#dfe9f5").pack(anchor="w", pady=(2, 8))
        ctk.CTkButton(mid_text, text="修改设置", width=80, height=28, command=lambda: self.show_page("mail")).pack(anchor="w")

        right = ctk.CTkFrame(data, fg_color="#0d1b28", corner_radius=0)
        right.grid(row=0, column=2, sticky="nsew", padx=(8, 14), pady=12)
        ctk.CTkLabel(right, text="📁", font=("Segoe UI Emoji", 30), text_color="#ffd36e").pack(side="left", padx=(18, 12), pady=12)
        right_text = ctk.CTkFrame(right, fg_color="transparent")
        right_text.pack(side="left", fill="both", expand=True, pady=12)
        ctk.CTkLabel(right_text, text="保存路径", text_color="#8ba0b8").pack(anchor="w")
        ctk.CTkLabel(right_text, textvariable=self.output_summary_var, text_color="#dfe9f5", wraplength=260).pack(anchor="w", pady=(2, 8))
        ctk.CTkButton(right_text, text="打开目录", width=80, height=28, command=self.open_output_dir).pack(anchor="w")

        recent_head = ctk.CTkFrame(page, fg_color="transparent")
        recent_head.pack(fill="x", padx=24, pady=(0, 6))
        ctk.CTkLabel(recent_head, text="最近记录", font=("Microsoft YaHei UI", 14, "bold"), text_color="#ffffff").pack(side="left")
        ctk.CTkButton(recent_head, text="查看全部记录 >", width=118, fg_color="transparent", hover_color="#10273b", text_color="#2f8cff", command=lambda: self.show_page("records")).pack(side="right")

        recent = ctk.CTkFrame(page, fg_color="#101f2d", corner_radius=8, border_width=1, border_color="#20384f")
        recent.pack(fill="both", expand=True, padx=24, pady=(0, 18))
        self.recent_list_frames.append((recent, 3, "home"))
        self.render_empty_recent(recent)
        return page

    def info_chip(self, parent, title: str, detail: str, color: str) -> ctk.CTkFrame:
        chip = ctk.CTkFrame(parent, fg_color="#101f2d", corner_radius=8, border_width=1, border_color="#1d3449")
        ctk.CTkLabel(chip, text=title, font=("Microsoft YaHei UI", 11, "bold"), text_color=color).pack(anchor="w", padx=10, pady=(7, 0))
        ctk.CTkLabel(chip, text=detail, font=("Microsoft YaHei UI", 9), text_color="#8ea3ba").pack(anchor="w", padx=10, pady=(1, 7))
        return chip

    def ctk_mode_card(self, parent, icon, title, desc, features, bg, accent, command) -> ctk.CTkFrame:
        card = ctk.CTkFrame(parent, fg_color=bg, corner_radius=10, border_width=1, border_color=accent)
        top = ctk.CTkFrame(card, fg_color="transparent")
        top.pack(fill="x", padx=20, pady=(18, 6))
        bubble = ctk.CTkFrame(top, width=48, height=48, fg_color=accent, corner_radius=24)
        bubble.pack(side="left")
        bubble.pack_propagate(False)
        ctk.CTkLabel(bubble, text=icon, font=("Segoe UI Emoji", 23), text_color="#ffffff").pack(expand=True)
        title_box = ctk.CTkFrame(top, fg_color="transparent")
        title_box.pack(side="left", fill="x", expand=True, padx=(14, 0))
        ctk.CTkLabel(title_box, text=title, font=("Microsoft YaHei UI", 15, "bold"), text_color="#ffffff").pack(anchor="w")
        ctk.CTkLabel(title_box, text=desc, font=("Microsoft YaHei UI", 11), text_color="#b8cce2").pack(anchor="w", pady=(2, 0))
        ctk.CTkFrame(card, fg_color="#ffffff", height=1).pack(fill="x", padx=20, pady=(8, 10))
        ctk.CTkLabel(card, text="功能特点：", font=("Microsoft YaHei UI", 11, "bold"), text_color=accent).pack(anchor="w", padx=22, pady=(0, 4))
        for feature in features:
            ctk.CTkLabel(card, text=f"✓  {feature}", font=("Microsoft YaHei UI", 10), text_color="#dcecff").pack(anchor="w", padx=22, pady=1)
        ctk.CTkButton(
            card,
            text="启用此模式",
            command=command,
            height=36,
            corner_radius=6,
            fg_color=accent,
            hover_color="#1e73d8" if accent == "#2f8cff" else "#2dbf70",
            font=("Microsoft YaHei UI", 13, "bold"),
        ).pack(fill="x", padx=22, pady=(12, 18))
        return card

    def ctk_records_page(self) -> ctk.CTkFrame:
        page = self.ctk_page()
        self.ctk_title(page, "记录查看", "查看运行记录、导出日志或清理旧文件")
        actions = ctk.CTkFrame(page, fg_color="transparent")
        actions.pack(fill="x", padx=32, pady=(0, 14))
        for text, cmd in [
            ("刷新记录", self.load_recent_logs),
            ("打开保存目录", self.open_output_dir),
            ("打开日志目录", self.open_logs_dir),
            ("导出日志 zip", self.export_logs),
            ("清理超限文件", self.cleanup_storage),
        ]:
            ctk.CTkButton(actions, text=text, command=cmd, width=108, height=36, corner_radius=6).pack(side="left", padx=(0, 10))
        panel = ctk.CTkScrollableFrame(
            page,
            fg_color="#101f2d",
            corner_radius=8,
            border_width=1,
            border_color="#20384f",
            scrollbar_button_color="#24445f",
            scrollbar_button_hover_color="#2f5f86",
        )
        panel.pack(fill="both", expand=True, padx=32, pady=(0, 26))
        self.recent_list_frames.append((panel, 60, "full"))
        self.render_empty_recent(panel)
        return page

    def ctk_form_row(self, parent, label, var, show=None, button=None) -> None:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=22, pady=8)
        ctk.CTkLabel(row, text=label, width=150, anchor="w", text_color="#c8d8e9", font=("Microsoft YaHei UI", 13)).pack(side="left")
        entry = ctk.CTkEntry(row, textvariable=var, show=show, height=36, fg_color="#0d1b28", border_color="#263f58")
        entry.pack(side="left", fill="x", expand=True)
        if button:
            text, cmd = button
            ctk.CTkButton(row, text=text, command=cmd, width=82, height=34).pack(side="left", padx=(10, 0))

    def ctk_settings_page(self) -> ctk.CTkFrame:
        page = self.ctk_page()
        self.ctk_title(page, "设置中心", "调整触发规则、截图频率、本地保存和存储上限")
        scroll = ctk.CTkScrollableFrame(page, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=24, pady=(0, 18))

        form = ctk.CTkFrame(scroll, fg_color="#101f2d", corner_radius=10, border_width=1, border_color="#20384f")
        form.pack(fill="x", padx=0, pady=(0, 14))
        self.ctk_form_row(form, "保存目录", self.output_dir_var, button=("选择", self.pick_output_dir))
        row = ctk.CTkFrame(form, fg_color="transparent")
        row.pack(fill="x", padx=22, pady=8)
        ctk.CTkLabel(row, text="图片格式", width=150, anchor="w", text_color="#c8d8e9").pack(side="left")
        ctk.CTkComboBox(row, variable=self.format_var, values=["jpg", "png"], height=36).pack(side="left", fill="x", expand=True)
        row2 = ctk.CTkFrame(form, fg_color="transparent")
        row2.pack(fill="x", padx=22, pady=8)
        ctk.CTkLabel(row2, text="输出方式", width=150, anchor="w", text_color="#c8d8e9").pack(side="left")
        ctk.CTkComboBox(row2, variable=self.output_target_var, values=["local", "email"], height=36).pack(side="left", fill="x", expand=True)
        self.ctk_form_row(form, "模式一闲置阈值（秒）", self.idle_var)
        self.ctk_form_row(form, "截图间隔（秒）", self.screen_interval_var)
        self.ctk_form_row(form, "摄像头间隔（秒）", self.camera_interval_var)
        self.ctk_form_row(form, "本地文件上限（MB）", self.storage_limit_var)
        ctk.CTkCheckBox(form, text="模式一立即布防：下一次键鼠活动直接锁屏", variable=self.immediate_guard_var).pack(anchor="w", padx=22, pady=(10, 6))
        ctk.CTkCheckBox(form, text="模式一触发前显示警告提示", variable=self.warning_var).pack(anchor="w", padx=22, pady=(4, 18))
        shortcut_box = ctk.CTkFrame(scroll, fg_color="#101f2d", corner_radius=10, border_width=1, border_color="#20384f")
        shortcut_box.pack(fill="x", padx=0, pady=(0, 14))
        ctk.CTkLabel(shortcut_box, text="快捷键设置", font=("Microsoft YaHei UI", 13, "bold"), text_color="#ffffff").pack(anchor="w", padx=22, pady=(14, 4))
        grid = ctk.CTkFrame(shortcut_box, fg_color="transparent")
        grid.pack(fill="x", padx=16, pady=(0, 14))
        shortcut_rows = [
            ("模式一", self.shortcut_guard_var),
            ("模式二", self.shortcut_record_var),
            ("停止", self.shortcut_stop_var),
            ("保存", self.shortcut_save_var),
            ("打开目录", self.shortcut_open_var),
            ("导出日志", self.shortcut_export_var),
            ("刷新记录", self.shortcut_refresh_var),
        ]
        for index, (label, var) in enumerate(shortcut_rows):
            row = index // 2
            col = index % 2
            item = ctk.CTkFrame(grid, fg_color="transparent")
            item.grid(row=row, column=col, sticky="ew", padx=6, pady=5)
            ctk.CTkLabel(item, text=label, width=72, anchor="w", text_color="#c8d8e9").pack(side="left")
            ctk.CTkEntry(item, textvariable=var, height=30, fg_color="#0d1b28", border_color="#263f58").pack(side="left", fill="x", expand=True)
        grid.grid_columnconfigure((0, 1), weight=1)
        help_line = ctk.CTkLabel(
            shortcut_box,
            text="格式示例：Ctrl+1、Ctrl+Shift+K、Alt+O、F5、Esc。保存后立即生效。",
            font=("Microsoft YaHei UI", 11),
            text_color="#8ea3ba",
        )
        help_line.pack(anchor="w", padx=22, pady=(0, 14))

        tools = ctk.CTkFrame(scroll, fg_color="transparent")
        tools.pack(fill="x", padx=0, pady=(0, 12))
        for text, cmd, color in [
            ("保存设置", self.save_config, "#2f8cff"),
            ("测试截图", self.test_screenshot, "#1f3c57"),
            ("测试摄像头", self.test_camera, "#1f3c57"),
            ("停止监控", self.stop_all, "#7c2a37"),
        ]:
            ctk.CTkButton(tools, text=text, command=cmd, fg_color=color, width=108, height=40, corner_radius=6).pack(side="left", padx=(0, 10))
        return page

    def ctk_mail_page(self) -> ctk.CTkFrame:
        page = self.ctk_page()
        self.ctk_title(page, "邮箱设置", "填写 SMTP 信息后，可将照片、截图或日志作为附件发送")
        form = ctk.CTkFrame(page, fg_color="#101f2d", corner_radius=10, border_width=1, border_color="#20384f")
        form.pack(fill="x", padx=32, pady=(0, 14))
        self.ctk_form_row(form, "SMTP 主机", self.smtp_host_var)
        self.ctk_form_row(form, "SMTP 端口", self.smtp_port_var)
        self.ctk_form_row(form, "SMTP 用户名", self.smtp_user_var)
        self.ctk_form_row(form, "SMTP 密码/授权码", self.smtp_password_var, show="*")
        self.ctk_form_row(form, "收件邮箱", self.mail_to_var)
        ctk.CTkCheckBox(form, text="触发后实时发送附件", variable=self.email_realtime_var).pack(anchor="w", padx=22, pady=(10, 18))

        guide = ctk.CTkFrame(page, fg_color="#0d1b28", corner_radius=8, border_width=1, border_color="#244158")
        guide.pack(fill="x", padx=32, pady=(0, 14))
        ctk.CTkLabel(
            guide,
            text="QQ 邮箱配置说明",
            font=("Microsoft YaHei UI", 13, "bold"),
            text_color="#ffffff",
        ).pack(anchor="w", padx=18, pady=(12, 4))
        ctk.CTkLabel(
            guide,
            text=(
                "1. 打开 QQ 邮箱网页版，在 设置 > 账号 中开启 POP3/SMTP 或 IMAP/SMTP 服务。\n"
                "2. 按提示获取“授权码”，这里填写授权码，不要填写 QQ 登录密码。\n"
                "3. SMTP 主机填 smtp.qq.com，端口填 587，用户名填完整 QQ 邮箱，例如 123456@qq.com。\n"
                "4. 收件邮箱可以填同一个 QQ 邮箱，也可以填其他接收邮箱。保存后点击“发送测试邮件”。"
            ),
            justify="left",
            anchor="w",
            wraplength=780,
            font=("Microsoft YaHei UI", 12),
            text_color="#b8cce2",
        ).pack(fill="x", padx=18, pady=(0, 12))
        tools = ctk.CTkFrame(page, fg_color="transparent")
        tools.pack(fill="x", padx=32)
        ctk.CTkButton(tools, text="保存邮件设置", command=self.save_config, width=128, height=40).pack(side="left", padx=(0, 10))
        ctk.CTkButton(tools, text="发送测试邮件", command=self.test_email, width=128, height=40, fg_color="#1f3c57").pack(side="left")
        return page

    def ctk_help_page(self) -> ctk.CTkFrame:
        page = self.ctk_page()
        self.ctk_title(page, "帮助文档", "使用说明、作者联系方式和广告信息")
        box = ctk.CTkTextbox(page, fg_color="#101f2d", border_width=1, border_color="#20384f", corner_radius=10, font=("Microsoft YaHei UI", 13))
        box.pack(fill="both", expand=True, padx=32, pady=(0, 26))
        box.insert(
            "1.0",
            (
                "模式一：点击启用后，默认 1.5 秒布防，检测到下一次键鼠活动后先拍照或截图，再调用 Windows 锁屏。\n\n"
                "模式二：定时截图、尝试摄像头拍照，并记录窗口标题和键鼠活动发生时间。\n\n"
                "功能范围：键鼠检测、闲置后触发、立即布防、摄像头拍照、屏幕截图、本地保存、SMTP 邮件、日志导出、容量清理。\n\n"
                "快捷键：可在设置中心自定义。默认 Ctrl+1 启动模式一，Ctrl+2 启动模式二，Esc 停止监控，Ctrl+S 保存设置，Ctrl+O 打开保存目录，Ctrl+E 导出日志，F5 刷新记录。\n\n"
                "建议设置：如果只是防别人临时碰电脑，使用模式一；如果要记录自己离开后一段时间的使用情况，使用模式二。\n\n"
                "保存目录：默认和 exe 在同级目录，照片、截图、日志会按时间戳命名，方便回查。\n\n"
                "QQ 邮箱配置：先登录 QQ 邮箱网页版，在 设置 > 账号 中开启 POP3/SMTP 或 IMAP/SMTP 服务，并获取授权码。"
                "软件里填写 SMTP 主机 smtp.qq.com、端口 587、SMTP 用户名为完整 QQ 邮箱、SMTP 密码/授权码为刚生成的授权码。"
                "收件邮箱可填写自己的 QQ 邮箱，保存后点击“发送测试邮件”确认可用。\n\n"
                "隐私说明：键盘事件只记录发生时间，不保存具体按键内容。\n\n"
                f"作者名称：{AUTHOR_NAME}\n联系方式：{CONTACT_TEXT}\n广告内容：{AD_TEXT}\n官网：{AD_SITE}\n\n点击左侧微信号或广告文案可复制微信号。\n"
            ),
        )
        box.configure(state="disabled")
        return page

    def render_empty_recent(self, parent, mode: str = "full") -> None:
        header = ctk.CTkFrame(parent, fg_color="#142638", corner_radius=0)
        header.pack(fill="x", padx=1, pady=(1, 0))
        columns = [("时间", 126), ("事件", 112), ("说明", 360)] if mode == "home" else [
            ("时间", 128),
            ("事件", 120),
            ("说明", 260),
            ("预览", 54),
            ("处理方式", 92),
            ("操作", 126),
        ]
        for text, width in columns:
            ctk.CTkLabel(header, text=text, width=width, anchor="w", font=("Microsoft YaHei UI", 12, "bold"), text_color="#cddbeb").pack(side="left", padx=4, pady=10)

    def apply_dark_style(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", background="#0d1c2b", fieldbackground="#0d1c2b", foreground="#e7eef8", rowheight=34)
        style.configure("Treeview.Heading", background="#13283b", foreground="#dce8f7", font=("Microsoft YaHei UI", 10, "bold"))
        style.map("Treeview", background=[("selected", "#1f67b7")], foreground=[("selected", "#ffffff")])
        style.configure("TEntry", fieldbackground="#102236", foreground="#f3f7ff")
        style.configure("TCombobox", fieldbackground="#102236", foreground="#f3f7ff")
        style.configure("TCheckbutton", background="#071421", foreground="#d6e3f2")

    def start_window_drag(self, event) -> None:
        if self.is_maximized:
            return
        self.drag_start_x = event.x_root - self.root.winfo_x()
        self.drag_start_y = event.y_root - self.root.winfo_y()

    def drag_window(self, event) -> None:
        if self.is_maximized:
            return
        x = event.x_root - self.drag_start_x
        y = event.y_root - self.drag_start_y
        self.root.geometry(f"+{x}+{y}")

    def minimize_window(self) -> None:
        self.root.overrideredirect(False)
        self.root.iconify()
        self.root.after(200, lambda: self.root.overrideredirect(True))

    def toggle_maximize(self) -> None:
        if self.is_maximized:
            self.root.geometry(self.normal_geometry)
            self.is_maximized = False
            return
        self.normal_geometry = self.root.geometry()
        width = self.root.winfo_screenwidth()
        height = self.root.winfo_screenheight()
        self.root.geometry(f"{width}x{height}+0+0")
        self.is_maximized = True

    def make_page(self) -> tk.Frame:
        frame = tk.Frame(self.content_frame, bg="#071421")  # type: ignore[arg-type]
        frame.place(relx=0, rely=0, relwidth=1, relheight=1)
        return frame

    def section_title(self, parent: tk.Frame, title: str, subtitle: str = "") -> None:
        row = tk.Frame(parent, bg="#071421")
        row.pack(fill="x", padx=30, pady=(24, 6))
        tk.Label(row, text="🛡", bg="#071421", fg="#2f8cff", font=("Segoe UI Emoji", 15)).pack(side="left", padx=(0, 8))
        tk.Label(row, text=title, bg="#071421", fg="#ffffff", font=("Microsoft YaHei UI", 17, "bold")).pack(side="left")
        if subtitle:
            tk.Label(parent, text=subtitle, bg="#071421", fg="#8fa4bd", font=("Microsoft YaHei UI", 10)).pack(
                anchor="w", padx=30, pady=(0, 20)
            )

    def card(self, parent: tk.Frame, bg: str = "#0d1c2b") -> tk.Frame:
        frame = tk.Frame(parent, bg=bg, highlightthickness=1, highlightbackground="#24415e")
        return frame

    def build_home_page(self) -> tk.Frame:
        page = self.make_page()
        self.section_title(page, "选择监控模式", "请选择一种监控模式，保护您的电脑安全")

        cards = tk.Frame(page, bg="#071421")
        cards.pack(fill="x", padx=30, pady=(0, 26))
        guard = self.card(cards, "#0f2946")
        guard.pack(side="left", fill="both", expand=True, padx=(0, 14), ipady=28)
        record = self.card(cards, "#0d3a2f")
        record.pack(side="left", fill="both", expand=True, padx=(14, 0), ipady=28)
        self.mode_card(
            guard,
            "🔒",
            "模式一：动了就锁屏拍照",
            "检测到有人操作您的电脑时，立即取证并锁屏。",
            ["检测到操作立即锁屏", "拍照或截图记录操作者", "可发送邮箱或保存本地"],
            "#2f8cff",
            self.start_guard_mode,
        )
        self.mode_card(
            record,
            "📷",
            "模式二：持续监控记录",
            "定时截图、拍照，并记录窗口与输入活动。",
            ["定时自动拍照", "记录窗口使用情况", "日志可导出和清理"],
            "#35c878",
            self.start_record_mode,
        )

        processing = self.card(page)
        processing.pack(fill="x", padx=30, pady=(0, 18), ipady=10)
        processing.grid_columnconfigure(0, weight=1, uniform="processing")
        processing.grid_columnconfigure(1, weight=1, uniform="processing")
        processing.grid_columnconfigure(2, weight=1, uniform="processing")

        local_col = tk.Frame(processing, bg="#0d1c2b")
        local_col.grid(row=0, column=0, sticky="nsew", padx=(18, 12), pady=14)
        mail_col = tk.Frame(processing, bg="#0d1c2b", highlightthickness=1, highlightbackground="#1f3347")
        mail_col.grid(row=0, column=1, sticky="nsew", padx=12, pady=14)
        folder_col = tk.Frame(processing, bg="#0d1c2b", highlightthickness=1, highlightbackground="#1f3347")
        folder_col.grid(row=0, column=2, sticky="nsew", padx=(12, 18), pady=14)

        tk.Label(local_col, text="数据处理方式", bg="#0d1c2b", fg="#ffffff", font=("Microsoft YaHei UI", 12, "bold")).pack(
            anchor="w", pady=(0, 8)
        )
        tk.Radiobutton(
            local_col,
            text="发送到邮箱",
            variable=self.output_target_var,
            value="email",
            bg="#0d1c2b",
            fg="#d6e3f2",
            selectcolor="#0d1c2b",
            activebackground="#0d1c2b",
            command=self.save_config,
        ).pack(anchor="w", pady=3)
        tk.Radiobutton(
            local_col,
            text="保存到本地",
            variable=self.output_target_var,
            value="local",
            bg="#0d1c2b",
            fg="#d6e3f2",
            selectcolor="#0d1c2b",
            activebackground="#0d1c2b",
            command=self.save_config,
        ).pack(anchor="w", pady=3)

        tk.Label(mail_col, text="✉", bg="#0d1c2b", fg="#d6e9ff", font=("Segoe UI Emoji", 30)).pack(side="left", padx=(18, 14), pady=12)
        mail_text = tk.Frame(mail_col, bg="#0d1c2b")
        mail_text.pack(side="left", fill="both", expand=True, pady=14)
        tk.Label(mail_text, text="当前邮箱", bg="#0d1c2b", fg="#9fb2cc").pack(anchor="w")
        tk.Label(mail_text, textvariable=self.mail_summary_var, bg="#0d1c2b", fg="#d6e3f2").pack(anchor="w", pady=(2, 8))
        tk.Button(mail_text, text="修改设置", command=lambda: self.show_page("mail"), bg="#193957", fg="#ffffff", relief="flat").pack(anchor="w")

        tk.Label(folder_col, text="📁", bg="#0d1c2b", fg="#ffd36e", font=("Segoe UI Emoji", 30)).pack(side="left", padx=(18, 14), pady=12)
        folder_text = tk.Frame(folder_col, bg="#0d1c2b")
        folder_text.pack(side="left", fill="both", expand=True, pady=14)
        tk.Label(folder_text, text="保存路径", bg="#0d1c2b", fg="#9fb2cc").pack(anchor="w")
        tk.Label(folder_text, textvariable=self.output_summary_var, bg="#0d1c2b", fg="#d6e3f2", wraplength=300).pack(anchor="w", pady=(2, 8))
        tk.Button(folder_text, text="打开目录", command=self.open_output_dir, bg="#193957", fg="#ffffff", relief="flat").pack(anchor="w")

        recent = self.card(page)
        recent.pack(fill="both", expand=True, padx=30, pady=(0, 24))
        top = tk.Frame(recent, bg="#0d1c2b")
        top.pack(fill="x", padx=14, pady=(12, 4))
        tk.Label(top, text="最近记录", bg="#0d1c2b", fg="#ffffff", font=("Microsoft YaHei UI", 12, "bold")).pack(side="left")
        tk.Button(top, text="查看全部记录 >", command=lambda: self.show_page("records"), bg="#0d1c2b", fg="#2f8cff", relief="flat").pack(
            side="right"
        )
        self.build_log_table(recent, height=4)
        return page

    def mode_card(self, parent, icon, title, desc, features, color, command) -> None:
        icon_bg = "#173c66" if color == "#2f8cff" else "#18563c"
        icon_box = tk.Frame(parent, bg=icon_bg, width=72, height=72)
        icon_box.pack(pady=(4, 18))
        icon_box.pack_propagate(False)
        tk.Label(icon_box, text=icon, bg=icon_bg, fg=color, font=("Segoe UI Emoji", 30)).pack(expand=True)
        tk.Label(parent, text=title, bg=parent["bg"], fg="#ffffff", font=("Microsoft YaHei UI", 15, "bold")).pack()
        tk.Label(parent, text=desc, bg=parent["bg"], fg="#c8d6e5", font=("Microsoft YaHei UI", 10), wraplength=380).pack(pady=(12, 22))
        tk.Frame(parent, bg="#31506c" if color == "#2f8cff" else "#2f644f", height=1).pack(fill="x", padx=38, pady=(0, 12))
        tk.Label(parent, text="功能特点：", bg=parent["bg"], fg=color, font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w", padx=42, pady=(0, 6))
        for item in features:
            tk.Label(parent, text=f"✓  {item}", bg=parent["bg"], fg="#d9ecff", anchor="w").pack(anchor="w", padx=42, pady=2)
        tk.Button(
            parent,
            text="启用此模式",
            command=command,
            bg=color,
            fg="#ffffff",
            activebackground=color,
            activeforeground="#ffffff",
            relief="flat",
            bd=0,
            font=("Microsoft YaHei UI", 12, "bold"),
            pady=10,
        ).pack(fill="x", padx=42, pady=(26, 0))

    def build_log_table(self, parent: tk.Frame, height: int = 12) -> None:
        self.log_text = ttk.Treeview(
            parent,
            columns=("time", "type", "content", "output", "action"),
            show="headings",
            height=height,
        )
        self.log_tables.append(self.log_text)
        for key, title, width in [
            ("time", "时间", 150),
            ("type", "事件类型", 120),
            ("content", "记录内容", 360),
            ("output", "处理方式", 130),
            ("action", "操作", 90),
        ]:
            self.log_text.heading(key, text=title)
            self.log_text.column(key, width=width, anchor="w")
        self.log_text.pack(fill="both", expand=True, padx=14, pady=(0, 14))

    def build_records_page(self) -> tk.Frame:
        page = self.make_page()
        self.section_title(page, "记录查看", "查看运行记录、打开保存目录、导出日志或清理旧文件")
        actions = tk.Frame(page, bg="#071421")
        actions.pack(fill="x", padx=30, pady=(0, 12))
        for text, cmd in [
            ("刷新记录", self.load_recent_logs),
            ("打开保存目录", self.open_output_dir),
            ("打开日志目录", self.open_logs_dir),
            ("导出日志 zip", self.export_logs),
            ("清理超限文件", self.cleanup_storage),
        ]:
            tk.Button(actions, text=text, command=cmd, bg="#193957", fg="#ffffff", relief="flat", padx=12, pady=8).pack(
                side="left", padx=(0, 8)
            )
        panel = self.card(page)
        panel.pack(fill="both", expand=True, padx=30, pady=(0, 24))
        self.build_log_table(panel, height=16)
        self.load_recent_logs()
        return page

    def build_settings_page(self) -> tk.Frame:
        page = self.make_page()
        self.section_title(page, "设置中心", "调整触发规则、截图频率、本地保存和存储上限")
        form = self.card(page)
        form.pack(fill="x", padx=30, pady=(0, 18), ipady=12)
        self._row(form, "保存目录", self.output_dir_var, button=("选择", self.pick_output_dir))
        self._combo_row(form, "图片格式", self.format_var, ["jpg", "png"])
        self._combo_row(form, "输出方式", self.output_target_var, ["local", "email"])
        self._row(form, "模式一闲置阈值（秒）", self.idle_var)
        self._row(form, "截图间隔（秒）", self.screen_interval_var)
        self._row(form, "摄像头间隔（秒）", self.camera_interval_var)
        self._row(form, "本地文件上限（MB）", self.storage_limit_var)
        tk.Checkbutton(
            form,
            text="模式一立即布防：下一次键鼠活动直接锁屏",
            variable=self.immediate_guard_var,
            bg="#0d1c2b",
            fg="#d6e3f2",
            selectcolor="#0d1c2b",
            activebackground="#0d1c2b",
        ).pack(anchor="w", padx=18, pady=6)
        tk.Checkbutton(
            form,
            text="模式一触发前显示警告提示",
            variable=self.warning_var,
            bg="#0d1c2b",
            fg="#d6e3f2",
            selectcolor="#0d1c2b",
            activebackground="#0d1c2b",
        ).pack(anchor="w", padx=18, pady=6)
        tools = tk.Frame(page, bg="#071421")
        tools.pack(fill="x", padx=30)
        for text, cmd, color in [
            ("保存设置", self.save_config, "#2f8cff"),
            ("测试截图", self.test_screenshot, "#193957"),
            ("测试摄像头", self.test_camera, "#193957"),
            ("停止监控", self.stop_all, "#6b2730"),
        ]:
            tk.Button(tools, text=text, command=cmd, bg=color, fg="#ffffff", relief="flat", padx=16, pady=10).pack(
                side="left", padx=(0, 10)
            )
        return page

    def build_mail_page(self) -> tk.Frame:
        page = self.make_page()
        self.section_title(page, "邮箱设置", "填写 SMTP 信息后，可将照片、截图或日志作为附件发送")
        form = self.card(page)
        form.pack(fill="x", padx=30, pady=(0, 18), ipady=12)
        self._row(form, "SMTP 主机", self.smtp_host_var)
        self._row(form, "SMTP 端口", self.smtp_port_var)
        self._row(form, "SMTP 用户名", self.smtp_user_var)
        self._row(form, "SMTP 密码/授权码", self.smtp_password_var, show="*")
        self._row(form, "收件邮箱", self.mail_to_var)
        tk.Checkbutton(
            form,
            text="触发后实时发送附件",
            variable=self.email_realtime_var,
            bg="#0d1c2b",
            fg="#d6e3f2",
            selectcolor="#0d1c2b",
            activebackground="#0d1c2b",
        ).pack(anchor="w", padx=18, pady=6)
        tools = tk.Frame(page, bg="#071421")
        tools.pack(fill="x", padx=30)
        tk.Button(tools, text="保存邮件设置", command=self.save_config, bg="#2f8cff", fg="#ffffff", relief="flat", padx=16, pady=10).pack(
            side="left", padx=(0, 10)
        )
        tk.Button(tools, text="发送测试邮件", command=self.test_email, bg="#193957", fg="#ffffff", relief="flat", padx=16, pady=10).pack(
            side="left"
        )
        return page

    def build_help_page(self) -> tk.Frame:
        page = self.make_page()
        self.section_title(page, "帮助文档", "使用说明、作者联系方式和广告信息")
        box = self.card(page)
        box.pack(fill="both", expand=True, padx=30, pady=(0, 24))
        text = tk.Text(box, bg="#0d1c2b", fg="#d6e3f2", relief="flat", wrap="word", font=("Microsoft YaHei UI", 11))
        text.pack(fill="both", expand=True, padx=16, pady=16)
        text.insert(
            "1.0",
            (
                "模式一：点击启用后，默认 1.5 秒布防，检测到下一次键鼠活动后先拍照或截图，再调用 Windows 锁屏。\n\n"
                "模式二：定时截图、尝试摄像头拍照，并记录窗口标题和键鼠活动发生时间。\n\n"
                "隐私说明：键盘事件只记录发生时间，不保存具体按键内容。\n\n"
                f"作者名称：{AUTHOR_NAME}\n联系方式：{CONTACT_TEXT}\n广告内容：{AD_TEXT}\n"
            ),
        )
        text.configure(state="disabled")
        return page

    def _row(self, parent, label: str, var: StringVar, button=None, show=None) -> None:
        bg = parent["bg"] if hasattr(parent, "keys") and "bg" in parent.keys() else "#0d1c2b"
        frame = tk.Frame(parent, bg=bg)
        frame.pack(fill="x", padx=10, pady=6)
        tk.Label(frame, text=label, width=18, anchor="w", bg=bg, fg="#d6e3f2").pack(side="left")
        entry = tk.Entry(frame, textvariable=var, show=show, bg="#102236", fg="#f3f7ff", insertbackground="#ffffff", relief="flat")
        entry.pack(side="left", fill="x", expand=True)
        if button:
            text, command = button
            tk.Button(frame, text=text, command=command, bg="#193957", fg="#ffffff", relief="flat").pack(side="left", padx=(8, 0))

    def _combo_row(self, parent, label: str, var: StringVar, values: list[str]) -> None:
        bg = parent["bg"] if hasattr(parent, "keys") and "bg" in parent.keys() else "#0d1c2b"
        frame = tk.Frame(parent, bg=bg)
        frame.pack(fill="x", padx=10, pady=6)
        tk.Label(frame, text=label, width=18, anchor="w", bg=bg, fg="#d6e3f2").pack(side="left")
        ttk.Combobox(frame, textvariable=var, values=values, state="readonly").pack(
            side="left", fill="x", expand=True
        )

    def show_page(self, key: str) -> None:
        self.active_nav_key = key
        for page_key, page in self.pages.items():
            if page_key == key:
                page.tkraise()
            btn = self.nav_buttons.get(page_key)
            if btn:
                active = page_key == key
                btn.configure(fg_color="#153b66" if active else "transparent")
                for child in getattr(btn, "nav_children", ()):
                    child.configure(text_color="#ffffff" if active else "#d6e3f2")
        if key in {"home", "records"}:
            self.load_recent_logs()

    def pick_output_dir(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.output_dir_var.get())
        if selected:
            self.output_dir_var.set(selected)

    def save_config(self) -> None:
        try:
            self.cfg.output_dir = self.output_dir_var.get().strip() or str(DEFAULT_OUTPUT_DIR)
            self.cfg.image_format = self.format_var.get()
            self.cfg.immediate_guard_trigger = self.immediate_guard_var.get()
            self.cfg.output_target = self.output_target_var.get()
            self.cfg.idle_seconds_before_guard_trigger = max(3, int(self.idle_var.get()))
            self.cfg.screenshot_interval_seconds = max(5, int(self.screen_interval_var.get()))
            self.cfg.camera_interval_seconds = max(10, int(self.camera_interval_var.get()))
            self.cfg.storage_limit_mb = max(10, int(self.storage_limit_var.get()))
            self.cfg.show_warning_before_lock = self.warning_var.get()
            self.cfg.email_realtime = self.email_realtime_var.get()
            self.cfg.smtp_host = self.smtp_host_var.get().strip()
            self.cfg.smtp_port = int(self.smtp_port_var.get())
            self.cfg.smtp_user = self.smtp_user_var.get().strip()
            self.cfg.smtp_password = self.smtp_password_var.get()
            self.cfg.mail_from = self.cfg.smtp_user
            self.cfg.mail_to = self.mail_to_var.get().strip()
            shortcuts = self.collect_shortcut_values()
            if not self.validate_shortcuts(shortcuts):
                return
            self.cfg.shortcut_guard_mode = shortcuts["guard"]
            self.cfg.shortcut_record_mode = shortcuts["record"]
            self.cfg.shortcut_stop = shortcuts["stop"]
            self.cfg.shortcut_save = shortcuts["save"]
            self.cfg.shortcut_open_dir = shortcuts["open"]
            self.cfg.shortcut_export_logs = shortcuts["export"]
            self.cfg.shortcut_refresh = shortcuts["refresh"]
            self.cfg.save()
            ensure_dirs(Path(self.cfg.output_dir))
            self.output_summary_var.set(self.compact_path(self.cfg.output_dir, 34))
            self.mail_summary_var.set(self.cfg.mail_to or "未配置")
            self.bind_shortcuts()
            self.add_ui_log("设置已保存")
        except ValueError:
            messagebox.showerror(APP_NAME, "时间间隔和端口必须是数字。")

    def collect_shortcut_values(self) -> dict[str, str]:
        return {
            "guard": self.shortcut_guard_var.get().strip() or "Ctrl+1",
            "record": self.shortcut_record_var.get().strip() or "Ctrl+2",
            "stop": self.shortcut_stop_var.get().strip() or "Esc",
            "save": self.shortcut_save_var.get().strip() or "Ctrl+S",
            "open": self.shortcut_open_var.get().strip() or "Ctrl+O",
            "export": self.shortcut_export_var.get().strip() or "Ctrl+E",
            "refresh": self.shortcut_refresh_var.get().strip() or "F5",
        }

    def validate_shortcuts(self, shortcuts: dict[str, str]) -> bool:
        normalized: dict[str, str] = {}
        for action, shortcut in shortcuts.items():
            event = self.shortcut_to_tk_event(shortcut)
            if not event:
                messagebox.showerror(APP_NAME, f"快捷键格式无效：{shortcut}")
                return False
            if event in normalized:
                messagebox.showerror(APP_NAME, f"快捷键冲突：{shortcut} 被重复使用。")
                return False
            normalized[event] = action
        return True

    def open_output_dir(self) -> None:
        self.save_config()
        path = Path(self.cfg.output_dir)
        ensure_dirs(path)
        subprocess.Popen(["explorer", str(path)])
        self.add_ui_log("已打开保存目录")

    def open_logs_dir(self) -> None:
        ensure_dirs(LOG_DIR)
        subprocess.Popen(["explorer", str(LOG_DIR)])
        self.add_ui_log("已打开日志目录")

    def test_screenshot(self) -> None:
        self.save_config()
        try:
            path = self.capture.screenshot("test_screen")
            self.add_ui_log(f"测试截图已保存：{path.name}")
            self.cleanup_storage(silent=True)
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"截图失败：{exc}")

    def test_camera(self) -> None:
        self.save_config()
        try:
            path = self.capture.camera_photo("test_camera")
            if path:
                self.add_ui_log(f"测试摄像头已保存：{path.name}")
                self.cleanup_storage(silent=True)
            else:
                self.add_ui_log("摄像头不可用，已改用截图测试")
                self.test_screenshot()
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"摄像头测试失败：{exc}")

    def test_email(self) -> None:
        self.save_config()
        try:
            note = LOG_DIR / f"mail_test_{now_stamp()}.txt"
            ensure_dirs(LOG_DIR)
            note.write_text(f"{APP_NAME} 测试邮件\n{datetime.now().isoformat(timespec='seconds')}\n", encoding="utf-8")
            self.mailer.send_files(f"{APP_NAME} 测试邮件", "如果您收到此邮件，说明 SMTP 配置可用。", [note])
            self.add_ui_log("测试邮件已发送")
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"发送测试邮件失败：{exc}")
            self.log.write("email_test_failed", {"reason": str(exc)})

    def output_files(self) -> list[Path]:
        path = Path(self.cfg.output_dir)
        if not path.exists():
            return []
        return [p for p in path.rglob("*") if p.is_file()]

    def cleanup_storage(self, silent: bool = False) -> None:
        if not silent:
            self.save_config()
        files = sorted(self.output_files(), key=lambda p: p.stat().st_mtime)
        limit = self.cfg.storage_limit_mb * 1024 * 1024
        total = sum(p.stat().st_size for p in files)
        removed = 0
        while total > limit and files:
            victim = files.pop(0)
            size = victim.stat().st_size
            victim.unlink(missing_ok=True)
            total -= size
            removed += 1
        self.log.write("storage_cleanup", {"removed": removed, "remaining_bytes": total})
        if not silent:
            self.add_ui_log(f"清理完成：删除 {removed} 个旧文件")

    def export_logs(self) -> None:
        self.save_config()
        ensure_dirs(LOG_DIR, Path(self.cfg.output_dir))
        zip_path = Path(self.cfg.output_dir) / f"logs_export_{now_stamp()}.zip"
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in LOG_DIR.glob("*.jsonl"):
                archive.write(path, arcname=path.name)
        self.add_ui_log(f"日志已导出：{zip_path.name}")

    def load_recent_logs(self) -> None:
        for table in self.log_tables:
            for item in table.get_children():
                table.delete(item)
        rows = []
        for path in sorted(LOG_DIR.glob("activity_*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for line in reversed(lines[-80:]):
                try:
                    row = json.loads(line)
                    row["_source_log"] = str(path)
                    rows.append(row)
                except json.JSONDecodeError:
                    continue
                if len(rows) >= 60:
                    break
            if len(rows) >= 60:
                break
        for row in rows:
            event = row.get("event", "")
            detail = row.get("detail", {})
            content = self.describe_event(event, detail)
            output = "已保存本地" if self.cfg.output_target == "local" else "发送到邮箱"
            for table in self.log_tables:
                table.insert("", "end", values=(self.format_record_time(row.get("time", "")), self.event_label(event), content, output, "查看"))
        self.recent_rows = rows
        self.render_ctk_recent_rows(rows)
        self.record_count_var.set(str(len(rows)))

    def render_ctk_recent_rows(self, rows: list[dict]) -> None:
        if not self.recent_list_frames:
            return
        self.preview_images = []
        for frame, limit, mode in self.recent_list_frames:
            for child in frame.winfo_children():
                child.destroy()
            self.render_empty_recent(frame, mode)
            visible = rows[:limit]
            if not visible:
                ctk.CTkLabel(frame, text="暂无记录", text_color="#7890aa", font=("Microsoft YaHei UI", 13)).pack(pady=24)
                continue
            for index, row in enumerate(visible):
                event = row.get("event", "")
                detail = row.get("detail", {})
                content = self.describe_event(event, detail)
                output = "已保存本地" if self.cfg.output_target == "local" else "发送到邮箱"
                line = ctk.CTkFrame(frame, fg_color="#0d1b28" if index % 2 else "#102131", corner_radius=0)
                line.pack(fill="x", padx=1)
                if mode == "home":
                    for text, width, color in [
                        (self.format_record_time(row.get("time", "")), 126, "#dce8f5"),
                        (self.event_label(event), 112, self.event_color(event)),
                        (content, 360, "#dce8f5"),
                    ]:
                        ctk.CTkLabel(
                            line,
                            text=str(text),
                            width=width,
                            anchor="w",
                            text_color=color,
                            font=("Microsoft YaHei UI", 12),
                        ).pack(side="left", padx=4, pady=8)
                    continue
                values = [
                    (self.format_record_time(row.get("time", "")), 128, "#dce8f5"),
                    (self.event_label(event), 120, self.event_color(event)),
                    (content, 260, "#dce8f5"),
                ]
                for text, width, color in values:
                    ctk.CTkLabel(
                        line,
                        text=str(text),
                        width=width,
                        anchor="w",
                        text_color=color,
                        font=("Microsoft YaHei UI", 12),
                    ).pack(side="left", padx=4, pady=9)
                self.record_preview_widget(line, row).pack(side="left", padx=4, pady=4)
                ctk.CTkLabel(
                    line,
                    text=output,
                    width=92,
                    anchor="w",
                    text_color="#35d778",
                    font=("Microsoft YaHei UI", 12),
                ).pack(side="left", padx=4, pady=9)
                actions = ctk.CTkFrame(line, fg_color="transparent", width=146)
                actions.pack(side="left", padx=4, pady=5)
                for label, cmd, color in [
                    ("👁", lambda r=row: self.show_record_detail(r), "#1f3c57"),
                    ("📁", lambda r=row: self.open_record_target(r), "#1f3c57"),
                    ("🗑", lambda r=row: self.delete_record_target(r), "#70303a"),
                ]:
                    ctk.CTkButton(
                        actions,
                        text=label,
                        command=cmd,
                        width=40,
                        height=26,
                        fg_color=color,
                        hover_color="#2a5275" if color != "#70303a" else "#8a3b46",
                        font=("Segoe UI Emoji", 11),
                    ).pack(side="left", padx=(0, 5))

    def record_preview_widget(self, parent, row: dict):
        target = self.record_target_path(row)
        if target and target.exists() and target.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp", ".webp"}:
            try:
                image = Image.open(target)
                image.thumbnail((34, 34))
                preview = ctk.CTkImage(light_image=image.copy(), dark_image=image.copy(), size=(34, 34))
                self.preview_images.append(preview)
                return ctk.CTkLabel(parent, text="", image=preview, width=56)
            except OSError:
                pass
        event = str(row.get("event", ""))
        if "window" in event or "program" in event:
            icon = "🌐"
        elif "keyboard" in event:
            icon = "⌨"
        elif "camera" in event:
            icon = "📷"
        elif "screen" in event:
            icon = "🖼"
        else:
            icon = "📄"
        return ctk.CTkLabel(parent, text=icon, width=56, font=("Segoe UI Emoji", 20), text_color="#a8b8ca")

    def format_record_time(self, value: object) -> str:
        text = str(value or "")
        if not text:
            return ""
        try:
            return datetime.fromisoformat(text).strftime("%m-%d %H:%M:%S")
        except ValueError:
            return text[:19]

    def event_label(self, event: str) -> str:
        labels = {
            "guard_mode_started": "模式一启动",
            "record_mode_started": "模式二启动",
            "guard_triggered": "锁屏取证",
            "activity": "键鼠活动",
            "screenshot_saved": "截图保存",
            "camera_saved": "拍照保存",
            "camera_unavailable": "摄像头不可用",
            "camera_capture_failed": "拍照失败",
            "email_sent": "邮件已发送",
            "email_skipped": "邮件未发送",
            "email_failed": "邮件失败",
            "email_test_failed": "测试邮件失败",
            "storage_cleanup": "存储清理",
            "file_deleted_from_record": "附件删除",
            "stopped": "监控停止",
        }
        return labels.get(str(event), "系统记录")

    def event_color(self, event: str) -> str:
        event = str(event)
        if event in {"guard_triggered", "email_failed", "email_test_failed", "camera_capture_failed"}:
            return "#ff7777"
        if event in {"record_mode_started", "activity", "screenshot_saved", "camera_saved"}:
            return "#35d778"
        if event in {"guard_mode_started", "email_sent", "storage_cleanup"}:
            return "#2f8cff"
        return "#dce8f5"

    def activity_label(self, activity: object) -> str:
        labels = {
            "keyboard_activity": "键盘输入",
            "mouse_click": "鼠标点击",
            "mouse_move": "鼠标移动",
        }
        return labels.get(str(activity), str(activity))

    def describe_event(self, event: str, detail: dict) -> str:
        event = str(event)
        detail = detail if isinstance(detail, dict) else {}
        if event == "guard_mode_started":
            mode = "立即触发" if detail.get("immediate") else f"闲置 {detail.get('idle_seconds', '')} 秒后触发"
            return f"模式一已布防：{mode}"
        if event == "record_mode_started":
            return "模式二已开始持续记录"
        if event == "stopped":
            return "监控已停止"
        if event == "guard_triggered":
            activity = self.activity_label(detail.get("activity", "键鼠活动"))
            idle = detail.get("idle_seconds")
            return f"检测到{activity}，已执行锁屏取证" if idle in (None, "") else f"闲置 {idle} 秒后检测到{activity}，已执行锁屏取证"
        if event == "activity":
            activity = self.activity_label(detail.get("activity", "键鼠活动"))
            window = detail.get("active_window")
            return f"{activity}，当前窗口：{window}" if window else f"检测到{activity}"
        if event in {"screenshot_saved", "camera_saved", "file_deleted_from_record"} and "path" in detail:
            prefix = "截图已保存" if event == "screenshot_saved" else "照片已保存" if event == "camera_saved" else "附件已删除"
            return f"{prefix}：{Path(str(detail['path'])).name}"
        if event == "email_sent":
            count = len(detail.get("files", [])) if isinstance(detail.get("files"), list) else 0
            return f"邮件发送成功，附件 {count} 个"
        if event in {"email_skipped", "email_failed", "email_test_failed", "camera_unavailable", "camera_capture_failed"}:
            return f"原因：{detail.get('reason', '未提供')}"
        if event == "storage_cleanup":
            return f"已删除 {detail.get('removed', 0)} 个旧文件"
        if "path" in detail:
            return Path(str(detail["path"])).name
        if "title" in detail:
            return str(detail["title"])
        if "activity" in detail:
            return f"检测到{self.activity_label(detail['activity'])}"
        if "reason" in detail:
            return str(detail["reason"])
        if detail:
            return json.dumps(detail, ensure_ascii=False)
        return self.event_label(event)

    def record_target_path(self, row: dict) -> Path | None:
        detail = row.get("detail", {})
        if isinstance(detail, dict) and detail.get("path"):
            return Path(str(detail["path"]))
        return None

    def show_record_detail(self, row: dict) -> None:
        event = row.get("event", "")
        detail = row.get("detail", {})
        target = self.record_target_path(row)
        lines = [
            f"时间：{self.format_record_time(row.get('time', ''))}",
            f"事件：{self.event_label(event)}",
            f"内容：{self.describe_event(event, detail if isinstance(detail, dict) else {})}",
            f"处理方式：{'已保存本地' if self.cfg.output_target == 'local' else '发送到邮箱'}",
        ]
        if target:
            lines.append(f"文件：{target}")
        if row.get("_source_log"):
            lines.append(f"日志：{row.get('_source_log')}")
        messagebox.showinfo("记录详情", "\n".join(lines))

    def open_record_target(self, row: dict) -> None:
        target = self.record_target_path(row)
        if target and target.exists():
            subprocess.Popen(["explorer", "/select,", str(target)])
            return
        source = row.get("_source_log")
        if source and Path(str(source)).exists():
            subprocess.Popen(["explorer", "/select,", str(source)])
            return
        self.open_logs_dir()

    def delete_record_target(self, row: dict) -> None:
        target = self.record_target_path(row)
        if not target or not target.exists():
            messagebox.showinfo(APP_NAME, "这条记录没有可删除的附件文件。")
            return
        if not messagebox.askyesno(APP_NAME, f"确定删除这个文件？\n{target.name}"):
            return
        try:
            target.unlink()
            self.log.write("file_deleted_from_record", {"path": str(target)})
            self.add_ui_log(f"已删除附件：{target.name}")
            self.load_recent_logs()
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"删除失败：{exc}")

    def copy_wechat(self) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(WECHAT_ID)
        self.root.update_idletasks()
        self.add_ui_log(f"已复制微信号：{WECHAT_ID}")

    def bind_shortcuts(self) -> None:
        for key in self.shortcut_bindings:
            self.root.unbind_all(key)
        self.shortcut_bindings = []
        bindings = [
            (self.cfg.shortcut_guard_mode, lambda _event: self.start_guard_mode()),
            (self.cfg.shortcut_record_mode, lambda _event: self.start_record_mode()),
            (self.cfg.shortcut_stop, lambda _event: self.stop_all()),
            (self.cfg.shortcut_save, lambda _event: self.save_config()),
            (self.cfg.shortcut_open_dir, lambda _event: self.open_output_dir()),
            (self.cfg.shortcut_export_logs, lambda _event: self.export_logs()),
            (self.cfg.shortcut_refresh, lambda _event: self.load_recent_logs()),
        ]
        for shortcut, callback in bindings:
            tk_event = self.shortcut_to_tk_event(shortcut)
            if not tk_event:
                continue
            self.root.bind_all(tk_event, callback)
            self.shortcut_bindings.append(tk_event)

    def shortcut_to_tk_event(self, shortcut: str) -> str | None:
        raw = shortcut.strip()
        if not raw:
            return None
        parts = [part.strip() for part in raw.replace("-", "+").split("+") if part.strip()]
        if not parts:
            return None
        key = parts[-1]
        modifiers = {part.lower() for part in parts[:-1]}
        prefix = []
        if "ctrl" in modifiers or "control" in modifiers:
            prefix.append("Control")
        if "alt" in modifiers:
            prefix.append("Alt")
        if "shift" in modifiers:
            prefix.append("Shift")
        aliases = {
            "esc": "Escape",
            "escape": "Escape",
            "space": "space",
            "enter": "Return",
            "return": "Return",
            "del": "Delete",
            "delete": "Delete",
        }
        key_name = aliases.get(key.lower(), key)
        if len(key_name) == 1:
            key_name = key_name.lower()
            if prefix:
                return f"<{'-'.join(prefix)}-Key-{key_name}>"
            return f"<Key-{key_name}>"
        if key_name.upper().startswith("F") and key_name[1:].isdigit():
            key_name = key_name.upper()
        if prefix:
            return f"<{'-'.join(prefix)}-{key_name}>"
        return f"<{key_name}>"

    def start_guard_mode(self) -> None:
        self.save_config()
        self.stop_recording.set()
        self.mode = "guard"
        self.guard_triggered = False
        self.guard_grace_until = time.monotonic() + 1.5
        self.last_activity = time.monotonic()
        self.last_cursor_pos = self.get_cursor_position()
        self.pressed_keys = self.current_pressed_keys()
        self.hooks.start()
        if self.cfg.immediate_guard_trigger:
            self.status_var.set("模式一运行中：1.5 秒后布防，下一次键鼠活动会触发锁屏取证")
        else:
            self.status_var.set("模式一运行中：达到闲置阈值后，下一次键鼠活动会触发锁屏取证")
        self.log.write(
            "guard_mode_started",
            {
                "idle_seconds": self.cfg.idle_seconds_before_guard_trigger,
                "immediate": self.cfg.immediate_guard_trigger,
            },
        )
        self.add_ui_log("模式一已启动")

    def start_record_mode(self) -> None:
        self.save_config()
        self.mode = "record"
        self.guard_triggered = False
        self.last_cursor_pos = self.get_cursor_position()
        self.pressed_keys = self.current_pressed_keys()
        self.stop_recording.clear()
        self.hooks.start()
        self.status_var.set("模式二运行中：正在记录截图、窗口标题和键鼠活动计数")
        self.log.write("record_mode_started")
        self.add_ui_log("模式二已启动")
        threading.Thread(target=self.record_loop, name="RecordLoop", daemon=True).start()

    def stop_all(self) -> None:
        self.mode = "idle"
        self.stop_recording.set()
        self.hooks.stop()
        self.status_var.set("已停止")
        self.log.write("stopped")
        self.add_ui_log("已停止")

    def on_hook_event(self, event: str) -> None:
        self.events.put(event)

    def process_events(self) -> None:
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            self.handle_activity(event)
        self.root.after(250, self.process_events)

    def get_cursor_position(self) -> tuple[int, int]:
        point = POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
        return point.x, point.y

    def current_pressed_keys(self) -> set[int]:
        user32 = ctypes.windll.user32
        pressed: set[int] = set()
        for vk in range(1, 256):
            if user32.GetAsyncKeyState(vk) & 0x8000:
                pressed.add(vk)
        return pressed

    def poll_input_state(self) -> None:
        if self.mode != "idle":
            now = time.monotonic()
            current_pos = self.get_cursor_position()
            if current_pos != self.last_cursor_pos and now - self.last_polled_mouse_event >= 1.0:
                self.last_polled_mouse_event = now
                self.last_cursor_pos = current_pos
                self.handle_activity("mouse_move")
            elif current_pos != self.last_cursor_pos:
                self.last_cursor_pos = current_pos

            current_keys = self.current_pressed_keys()
            if current_keys - self.pressed_keys:
                self.handle_activity("keyboard_activity")
            self.pressed_keys = current_keys
        self.root.after(250, self.poll_input_state)

    def handle_activity(self, event: str) -> None:
        current = time.monotonic()
        if self.mode == "guard" and current < self.guard_grace_until:
            self.last_activity = current
            return
        idle_for = current - self.last_activity
        self.last_activity = current

        if self.mode == "record":
            title = active_window_title()
            detail = {"activity": event}
            if title and title != self.last_window_title:
                self.last_window_title = title
                detail["active_window"] = title
            self.log.write("activity", detail)
            self.add_ui_log(f"记录：{event}")
            return

        if self.mode == "guard" and not self.guard_triggered:
            threshold = self.cfg.idle_seconds_before_guard_trigger
            if self.cfg.immediate_guard_trigger or idle_for >= threshold:
                self.guard_triggered = True
                if self.cfg.immediate_guard_trigger:
                    self.add_ui_log(f"触发：检测到 {event}")
                else:
                    self.add_ui_log(f"触发：闲置 {int(idle_for)} 秒后检测到 {event}")
                threading.Thread(target=self.guard_action, args=(event, int(idle_for)), daemon=True).start()

    def guard_action(self, event: str, idle_for: int) -> None:
        self.log.write("guard_triggered", {"activity": event, "idle_seconds": idle_for})
        files: list[Path] = []
        if self.cfg.show_warning_before_lock:
            self.root.after(
                0,
                lambda: messagebox.showwarning(APP_NAME, "检测到闲置后的键鼠操作，即将锁屏并保存取证文件。"),
            )
            time.sleep(1)
        camera = self.capture.camera_photo("guard_camera")
        if camera:
            files.append(camera)
        else:
            files.append(self.capture.screenshot("guard_screen"))
        self.cleanup_storage(silent=True)

        if self.cfg.output_target == "email" and self.cfg.email_realtime:
            try:
                self.mailer.send_files(
                    f"{APP_NAME} 触发提醒 {now_stamp()}",
                    f"检测到闲置 {idle_for} 秒后的 {event}。",
                    files,
                )
            except Exception as exc:
                self.log.write("email_failed", {"reason": str(exc)})
        locked = lock_workstation()
        self.log.write("lock_workstation", {"ok": locked})
        if not locked:
            self.root.after(0, lambda: self.add_ui_log("锁屏调用失败：请检查当前 Windows 会话权限"))

    def record_loop(self) -> None:
        next_screen = 0.0
        next_camera = 0.0
        while not self.stop_recording.is_set() and self.mode == "record":
            now = time.monotonic()
            files: list[Path] = []
            if self.cfg.save_screenshots and now >= next_screen:
                files.append(self.capture.screenshot("record_screen"))
                next_screen = now + self.cfg.screenshot_interval_seconds
            if self.cfg.save_camera_images and now >= next_camera:
                camera = self.capture.camera_photo("record_camera")
                if camera:
                    files.append(camera)
                next_camera = now + self.cfg.camera_interval_seconds
            title = active_window_title()
            if title and title != self.last_window_title:
                self.last_window_title = title
                self.log.write("active_window", {"title": title})
            if files and self.cfg.output_target == "email" and self.cfg.email_realtime:
                try:
                    bundle = self.bundle_files(files)
                    self.mailer.send_files(
                        f"{APP_NAME} 行为记录 {now_stamp()}",
                        "自动记录模式生成的附件。",
                        [bundle],
                    )
                except Exception as exc:
                    self.log.write("email_failed", {"reason": str(exc)})
            if files:
                self.cleanup_storage(silent=True)
            time.sleep(1)

    def bundle_files(self, files: list[Path]) -> Path:
        zip_path = Path(self.cfg.output_dir) / f"record_bundle_{now_stamp()}.zip"
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for file in files:
                archive.write(file, arcname=file.name)
        self.log.write("zip_created", {"path": str(zip_path)})
        return zip_path

    def add_ui_log(self, text: str) -> None:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.last_run_var.set(f"上次运行：{ts}")
        for table in self.log_tables:
            table.insert("", 0, values=(ts, "界面操作", text, self.cfg.output_target, "查看"))
        if self.recent_list_frames:
            self.root.after(50, self.load_recent_logs)

    def close(self) -> None:
        self.stop_all()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    if os.name != "nt":
        raise SystemExit("此工具仅支持 Windows。")
    MonitorApp().run()
