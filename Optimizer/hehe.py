# -*- coding: utf-8 -*-
"""
Windows Optimizer & Cleaner - Ultimate Edition v9.0
====================================================
Tuong thich : Windows 7 SP1 (32/64-bit) & Windows 10/11 (32/64-bit)
Yeu cau     : Python 3.6+  |  Chay voi quyen Administrator

Nang cap v9.0 (tu v8.0):
  [MOI] Real-time Monitor tab  – bieu do CPU/RAM cap nhat moi 1s
  [MOI] Context Menu Integration – dang ky "Clean Here" vao Explorer
  [MOI] Plugin System – load file .py tu thu muc plugins/ khi khoi dong
  [MOI] Update Checker – so sanh phien ban voi file version.json
  [MOI] Notification Center – panel thong bao trong app
  [MOI] Restore Wizard – huong dan phuc hoi tung buoc
  [MOI] Windows Services GUI – xem/bat/tat service truc tiep tren Treeview
  [MOI] Hosts File Editor – xem/chinh sua file hosts de chan quang cao
  [MOI] Startup Delay Reducer – dat delay = 0 cho startup apps
  [MOI] Power Plan Viewer – hien thi va chuyen doi power plan truc tiep
  [MOI] Theme Palette Editor – chinh mau sac GUI tuy y luu vao settings
  [MOI] RAM Timeline Graph    – canvas ve duong bieu do RAM theo thoi gian
  [MOI] CPU Core Graph        – hien thi % su dung tung CPU core
  [CAI THIEN] Full Cleaner – parallel module execution (threading pool)
  [CAI THIEN] HTML Report v4  – them Monitor snapshot, plugin results
  [CAI THIEN] CLI nang cao    – autocomplete fuzzy, lenh moi

Nang cap v8.0 (tu v7.0):
  [MOI] Disk Analyzer – hien thi top 15 thu muc chiem nhieu dung luong
  [MOI] RAM Cleaner   – giai phong Standby Memory bang EmptyWorkingSet API
  [MOI] SSD Detect & TRIM – tu dong phan biet SSD/HDD, chay TRIM cho SSD
  [MOI] Pagefile Optimizer – tinh toan kich thuoc pagefile theo RAM
  [MOI] Hibernation Manager – tat/bat hibernation, giai phong hiberfil.sys
  [MOI] Event Log Cleaner – xoa Windows Event Log cu
  [MOI] Font Cache Rebuild – xoa va rebuild font cache de sua loi font
  [MOI] Cortana/Search Telemetry tweaks (Win10+)
  [MOI] Tab "Tools" trong GUI voi Disk Analyzer + RAM + Hibern + Pagefile
  [MOI] Before/After disk space comparison panel trong GUI
  [MOI] Thong bao Windows balloon tip sau khi hoan thanh
  [MOI] Export/Import settings file
  [MOI] Multi-drive disk usage bar chart trong sysinfo tab
  [CAI THIEN] CleanResult tich luy theo session, hien thi grand total
  [CAI THIEN] Them >20 registry tweak moi cho Win7 & Win10
  [CAI THIEN] Service list bo sung them 6 service it can thiet
  [CAI THIEN] CLI menu co them cac lenh moi tuong ung
"""

# ── stdlib ─────────────────────────────────────────────────────────────────
import csv
import ctypes
import io
import json
import logging
import os
import platform
import queue as _queue
import re
import shutil
import subprocess
import sys
import textwrap
import threading
import time
import traceback
import webbrowser
import winreg
from datetime import date, datetime
from pathlib import Path

# ── tkinter (optional – neu khong co se chay CLI) ───────────────────────────
try:
    import tkinter as tk
    from tkinter import ttk, messagebox, scrolledtext, filedialog
    TK_OK = True
except ImportError:
    TK_OK = False

# =============================================================================
#  METADATA
# =============================================================================
APP_NAME      = "Windows Optimizer & Cleaner"
APP_SUBTITLE  = "Ultimate Edition v9.0"
APP_VERSION   = "9.0"
WIN7_EOS      = date(2020, 1, 14)
WIN10_EOS     = date(2025, 10, 14)

# =============================================================================
#  OS DETECTION
# =============================================================================
def _get_win_ver():
    if platform.system() != "Windows":
        return (0, 0, 0)
    try:
        v = sys.getwindowsversion()
        return (v.major, v.minor, v.build)
    except Exception:
        return (0, 0, 0)

_WIN_VER      = _get_win_ver()
IS_WIN10_PLUS = _WIN_VER[0] >= 10
IS_WIN8_PLUS  = (_WIN_VER[0] >= 10) or (_WIN_VER[:2] >= (6, 2))
IS_WIN7       = _WIN_VER[:2] == (6, 1)
WIN_BUILD     = _WIN_VER[2]

# =============================================================================
#  PATHS
# =============================================================================
PROGRAM_DATA = os.environ.get("ProgramData",  r"C:\ProgramData")
APPDATA      = os.environ.get("APPDATA",      "")
LOCALAPPDATA = os.environ.get("LOCALAPPDATA", "")
USERPROFILE  = os.environ.get("USERPROFILE",  os.path.expanduser("~"))
WINDIR       = os.environ.get("SystemRoot",   r"C:\Windows")
TEMP         = os.environ.get("TEMP",         "")
TMP          = os.environ.get("TMP",          "")
SYSDRIVE     = os.environ.get("SystemDrive",  "C:")

APP_DIR              = os.path.join(PROGRAM_DATA, "WinOptimizerUltimate")
BACKUP_JSON          = os.path.join(APP_DIR, "backup.json")
SETTINGS_JSON        = os.path.join(APP_DIR, "settings.json")
DISABLED_STARTUP_DIR = os.path.join(APP_DIR, "disabled_startup")
REPORT_DIR           = os.path.join(APP_DIR, "reports")
LOG_DIR              = os.path.join(APP_DIR, "logs")

STARTUP_FOLDERS = [
    os.path.join(APPDATA,      r"Microsoft\Windows\Start Menu\Programs\Startup"),
    os.path.join(PROGRAM_DATA, r"Microsoft\Windows\Start Menu\Programs\StartUp"),
]

TEMP_DIRS = list(filter(None, [
    TEMP, TMP,
    os.path.join(LOCALAPPDATA, "Temp") if LOCALAPPDATA else "",
    os.path.join(WINDIR, "Temp"),
    os.path.join(WINDIR, "Prefetch"),
]))

RUN_REG_PATHS = [
    ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Run"),
    ("HKLM", r"Software\Microsoft\Windows\CurrentVersion\Run"),
    ("HKLM", r"Software\Wow6432Node\Microsoft\Windows\CurrentVersion\Run"),
]

# =============================================================================
#  LOGGING SYSTEM
# =============================================================================
_logger: logging.Logger = None

def _setup_logging():
    global _logger
    os.makedirs(LOG_DIR, exist_ok=True)
    log_file = os.path.join(LOG_DIR, datetime.now().strftime("%Y-%m-%d") + ".log")
    fmt = "[%(asctime)s] [%(levelname)-5s] %(message)s"
    logging.basicConfig(
        level=logging.DEBUG,
        format=fmt,
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ]
    )
    _logger = logging.getLogger(APP_NAME)

def log(msg: str, level: str = "info"):
    if _logger is None:
        _setup_logging()
    getattr(_logger, level.lower(), _logger.info)(msg)

# =============================================================================
#  SETTINGS PERSISTENCE
# =============================================================================
_DEFAULT_SETTINGS = {
    "auto_backup_before_tweak":  True,
    "auto_restore_point":        True,
    "confirm_before_extreme":    True,
    "clean_temp":                True,
    "clean_browser":             True,
    "clean_game":                True,
    "clean_office":              True,
    "clean_devtools":            True,
    "clean_system_files":        True,
    "clean_recycle":             True,
    "clean_security":            False,
    "clean_old_downloads":       False,
    "old_downloads_days":        30,
    "optimize_network":          True,
    "optimize_drives":           True,
    "schedule_enabled":          False,
    "schedule_time":             "03:00",
    "schedule_task_name":        "WinOptimizerUltimate_AutoClean",
    "last_run":                  None,
    "theme":                     "dark",
}

def load_settings() -> dict:
    if os.path.exists(SETTINGS_JSON):
        try:
            with open(SETTINGS_JSON, "r", encoding="utf-8") as f:
                saved = json.load(f)
            merged = dict(_DEFAULT_SETTINGS)
            merged.update(saved)
            return merged
        except Exception:
            pass
    return dict(_DEFAULT_SETTINGS)

def save_settings(s: dict):
    os.makedirs(APP_DIR, exist_ok=True)
    with open(SETTINGS_JSON, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)

# =============================================================================
#  REGISTRY CONSTANTS
# =============================================================================
REG_SZ        = 1
REG_EXPAND_SZ = 2
REG_DWORD     = 4
REG_QWORD     = 11

REG_TYPE_NAMES = {
    REG_SZ:        "REG_SZ",
    REG_EXPAND_SZ: "REG_EXPAND_SZ",
    REG_DWORD:     "REG_DWORD",
    REG_QWORD:     "REG_QWORD",
}

# ── Registry backup list ─────────────────────────────────────────────────────
_TOUCHED_REG_BASE = [
    ("HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\VisualEffects",  "VisualFXSetting",        REG_DWORD),
    ("HKCU", r"Control Panel\Desktop",                                             "MenuShowDelay",          REG_SZ),
    ("HKCU", r"Control Panel\Desktop",                                             "HungAppTimeout",         REG_SZ),
    ("HKCU", r"Control Panel\Desktop",                                             "WaitToKillAppTimeout",   REG_SZ),
    ("HKCU", r"Control Panel\Desktop",                                             "AutoEndTasks",           REG_SZ),
    ("HKCU", r"Control Panel\Mouse",                                               "MouseSpeed",             REG_SZ),
    ("HKCU", r"Control Panel\Mouse",                                               "MouseThreshold1",        REG_SZ),
    ("HKCU", r"Control Panel\Mouse",                                               "MouseThreshold2",        REG_SZ),
    ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced",       "TaskbarAnimations",      REG_DWORD),
    ("HKCU", r"Control Panel\Desktop\WindowMetrics",                               "MinAnimate",             REG_SZ),
    ("HKLM", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile",             "SystemResponsiveness",   REG_DWORD),
    ("HKLM", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile",             "NetworkThrottlingIndex", REG_DWORD),
    ("HKLM", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Games", "GPU Priority",           REG_DWORD),
    ("HKLM", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Games", "Priority",               REG_DWORD),
    ("HKLM", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Games", "Scheduling Category",    REG_SZ),
    ("HKLM", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Games", "SFIO Priority",          REG_SZ),
    # NEW v5: I/O priority
    ("HKLM", r"SYSTEM\CurrentControlSet\Control\PriorityControl",                  "Win32PrioritySeparation",REG_DWORD),
    # NEW v5: NTFS optimizations
    ("HKLM", r"SYSTEM\CurrentControlSet\Control\FileSystem",                       "NtfsDisableLastAccessUpdate", REG_DWORD),
    ("HKLM", r"SYSTEM\CurrentControlSet\Control\FileSystem",                       "NtfsMemoryUsage",        REG_DWORD),
]

_TOUCHED_REG_WIN10 = [
    ("HKCU", r"SOFTWARE\Microsoft\GameBar",                                        "AutoGameModeEnabled",    REG_DWORD),
    ("HKCU", r"SOFTWARE\Microsoft\GameBar",                                        "AllowAutoGameMode",      REG_DWORD),
    ("HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\GameDVR",                 "AppCaptureEnabled",      REG_DWORD),
    ("HKCU", r"System\GameConfigStore",                                            "GameDVR_Enabled",        REG_DWORD),
    ("HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Themes\Personalize",      "EnableTransparency",     REG_DWORD),
    ("HKLM", r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers",                  "HwSchMode",              REG_DWORD),
    # NEW v5: disable Xbox DVR overlay
    ("HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\GameDVR",                 "AudioEncodingBitrate",   REG_DWORD),
    ("HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\GameDVR",                 "MaximumRecordLength",    REG_DWORD),
]

def get_touched_registry():
    keys = list(_TOUCHED_REG_BASE)
    if IS_WIN10_PLUS:
        keys.extend(_TOUCHED_REG_WIN10)
    return keys

# =============================================================================
#  SERVICES
# =============================================================================
_LOW_RISK_SERVICES = [
    "DiagTrack",       # Connected User Experiences / Telemetry
    "dmwappushservice",# WAP Push / Telemetry
    "MapsBroker",      # Downloaded Maps Manager
    "Fax",             # Fax
    "WMPNetworkSvc",   # Windows Media Player Network Sharing
    "WerSvc",          # Windows Error Reporting
    "OneSyncSvc",      # Sync Host  (Win10)
    "RetailDemo",      # Retail Demo (Win10)
]
_EXTREME_SERVICES = ["SysMain", "WSearch"]
_WIN7_EXTRA_SERVICES = ["RemoteRegistry", "TabletInputService"]

def get_low_risk_services():
    return (_LOW_RISK_SERVICES + _WIN7_EXTRA_SERVICES) if IS_WIN7 else _LOW_RISK_SERVICES

# =============================================================================
#  SCHEDULED TASKS TO DISABLE
# =============================================================================
LOW_RISK_TASKS = [
    (r"\Microsoft\Windows\Application Experience\\",                   "Microsoft Compatibility Appraiser"),
    (r"\Microsoft\Windows\Application Experience\\",                   "ProgramDataUpdater"),
    (r"\Microsoft\Windows\Customer Experience Improvement Program\\",  "Consolidator"),
    (r"\Microsoft\Windows\Customer Experience Improvement Program\\",  "KernelCeipTask"),
    (r"\Microsoft\Windows\Customer Experience Improvement Program\\",  "UsbCeip"),
    (r"\Microsoft\Windows\Maps\\",                                     "MapsToastTask"),
    (r"\Microsoft\Windows\Maps\\",                                     "MapsUpdateTask"),
    (r"\Microsoft\Windows\Windows Error Reporting\\",                  "QueueReporting"),
    # NEW v5
    (r"\Microsoft\Windows\Autochk\\",                                  "Proxy"),
    (r"\Microsoft\Windows\DiskDiagnostic\\",                           "Microsoft-Windows-DiskDiagnosticDataCollector"),
]

# =============================================================================
#  GAME PREP
# =============================================================================
GAME_PREP_CANDIDATES = [
    ("chrome.exe","Google Chrome"), ("msedge.exe","Microsoft Edge"),
    ("firefox.exe","Mozilla Firefox"), ("opera.exe","Opera"),
    ("brave.exe","Brave"), ("vivaldi.exe","Vivaldi"),
    ("discord.exe","Discord"), ("Teams.exe","Microsoft Teams"),
    ("ms-teams.exe","Microsoft Teams (new)"), ("OneDrive.exe","OneDrive"),
    ("Dropbox.exe","Dropbox"), ("GoogleDriveFS.exe","Google Drive"),
    ("Creative Cloud.exe","Adobe Creative Cloud"),
    ("CCXProcess.exe","Adobe CCXProcess"),
    ("Spotify.exe","Spotify"), ("Telegram.exe","Telegram"),
    ("slack.exe","Slack"), ("zoom.exe","Zoom"),
    ("EpicGamesLauncher.exe","Epic Games Launcher"),
    ("RiotClientServices.exe","Riot Client"),
    ("GalaxyClient.exe","GOG Galaxy"),
]

# =============================================================================
#  TERMINAL UI HELPERS  (dung ca trong CLI va GUI thread log)
# =============================================================================
_ANSI = {
    "ok":   "\033[92m", "warn": "\033[93m",
    "err":  "\033[91m", "info": "\033[96m",
    "sect": "\033[95m", "bold": "\033[1m",
    "rst":  "\033[0m",
}

# Global GUI callback – duoc GUI set sau khi khoi tao
_gui_log_cb = None

# ── Hang doi thread-safe cho GUI log (tranh xung dot da luong Tkinter) ────────
# _emit() trong luong nen day vao hang doi nay thay vi goi GUI truc tiep.
# Luong chinh (Main Thread) cua GUI se doc hang doi nay qua process_ui_logs().
ui_log_queue: _queue.Queue = _queue.Queue()

def _emit(tag: str, prefix: str, msg: str):
    line = f"{prefix} {msg}"
    # Terminal
    print(f"{_ANSI.get(tag,'')}{line}{_ANSI['rst']}", flush=True)
    # File log
    lvl = "warning" if tag == "warn" else ("error" if tag == "err" else "info")
    log(msg, lvl)
    # GUI panel – day vao hang doi an toan, KHONG goi truc tiep tu luong nen.
    # Main Thread se doc va cap nhat giao dien qua process_ui_logs().
    if _gui_log_cb:
        ui_log_queue.put((tag, line))

def ok(msg):   _emit("ok",   "[OK]", msg)
def warn(msg): _emit("warn", "[!!]", msg)
def err(msg):  _emit("err",  "[XX]", msg)
def info(msg): _emit("info", "[ii]", msg)

def section(title: str):
    bar = "=" * 72
    print(f"\n{_ANSI['sect']}{bar}\n  {title}\n{bar}{_ANSI['rst']}", flush=True)
    log(f"=== {title} ===")
    if _gui_log_cb:
        ui_log_queue.put(("sect", f"{'─'*60}"))
        ui_log_queue.put(("sect", f"  {title}"))

# Global progress callback (set by GUI)
_gui_progress_cb = None

def _set_progress(pct: int, label: str = ""):
    bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
    print(f"\r  [{bar}] {pct:3d}%  {label:<40}", end="", flush=True)
    if _gui_progress_cb:
        # Dua vao hang doi de Main Thread xu ly, tranh goi truc tiep tu luong nen
        ui_log_queue.put(("__progress__", (pct, label)))

def _end_progress():
    print()

# =============================================================================
#  ADMIN / PROCESS HELPERS
# =============================================================================
def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False

def ensure_admin():
    if is_admin():
        return
    params = subprocess.list2cmdline(sys.argv)
    ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
    sys.exit(0)

# Co launch khong hien cua so console (quan trong khi chay duoi pythonw.exe / GUI).
# Neu khong co, MOI lenh subprocess se nhay 1 cua so den -> nhap nhay UI.
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

def run_cmd(cmd, timeout=120, shell=False):
    """
    [PATCHED v2] Ep buoc shell=False mac dinh de chong Command Injection.
    - Neu cmd la chuoi va shell=False: tu dong tach mang bang shlex.split (an toan).
    - Chi dung shell=True o nhung noi THUC SU can (wmic, powercfg co ky tu dac biet)
      va phai dam bao du lieu dau vao da duoc kiem tra truoc.
    [PATCHED v9.1] Them creationflags=CREATE_NO_WINDOW de khong nhay cua so console.
    """
    try:
        if isinstance(cmd, str) and not shell:
            import shlex
            cmd = shlex.split(cmd)  # Tach mang an toan, tranh cmd.exe dien giai ky tu dac biet
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout, shell=shell,
            encoding="utf-8", errors="replace",
            creationflags=_CREATE_NO_WINDOW,
        )
        return proc.returncode == 0, (proc.stdout or "").strip(), (proc.stderr or "").strip()
    except subprocess.TimeoutExpired as exc:
        return False, "", f"timeout sau {timeout}s: {exc}"
    except Exception as exc:
        return False, "", str(exc)

def ps(command: str, timeout=120):
    return run_cmd([
        "powershell", "-NoProfile", "-NonInteractive",
        "-ExecutionPolicy", "Bypass", "-Command", command,
    ], timeout=timeout, shell=False)

def wmic(query: str, timeout=60) -> str:
    # [PATCHED v9.1] shell=False -> run_cmd tu shlex.split, tranh cmd.exe injection.
    ok_, out, _ = run_cmd(f"wmic {query}", timeout=timeout, shell=False)
    return out if ok_ else ""

def wmic_val(query: str, field: str) -> str:
    out = wmic(f"{query} /value")
    for line in out.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            if k.strip().lower() == field.strip().lower():
                return v.strip()
    return ""

def extract_guid(text: str):
    m = re.search(
        r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})",
        text or ""
    )
    return m.group(1) if m else None

# =============================================================================
#  FILE SYSTEM HELPERS
# =============================================================================
def ensure_dirs():
    for d in [APP_DIR, DISABLED_STARTUP_DIR, REPORT_DIR, LOG_DIR]:
        os.makedirs(d, exist_ok=True)

def sanitize_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._ -]+", "_", name or "item")
    return (cleaned.strip(".") or "item")

def fmt_bytes(n: int) -> str:
    if n >= 1 << 30: return f"{n/(1<<30):.2f} GB"
    if n >= 1 << 20: return f"{n/(1<<20):.1f} MB"
    if n >= 1 << 10: return f"{n/(1<<10):.0f} KB"
    return f"{n} B"

def is_junction(path: str) -> bool:
    """
    Kiem tra xem path co phai Junction Point / Symlink hay khong.
    [PATCH - Loi #8 Goi y] Tranh xoa nham du lieu goc qua reparse point.
    """
    try:
        return bool(os.stat(path, follow_symlinks=False).st_reparse_tag)
    except AttributeError:
        # Python < 3.8 hoac Windows khong ho tro: dung GetFileAttributes
        try:
            attrs = ctypes.windll.kernel32.GetFileAttributesW(path)
            FILE_ATTRIBUTE_REPARSE_POINT = 0x400
            return bool(attrs != 0xFFFFFFFF and attrs & FILE_ATTRIBUTE_REPARSE_POINT)
        except Exception:
            return False
    except Exception:
        return False

def _del_dir_contents(path: str):
    if not path:
        return 0, 0

    # [PATCHED v2] Chuan hoa duong dan tuyet doi truoc moi tac dong
    try:
        p = Path(path).resolve()
    except Exception:
        return 0, 0

    # Danh sach den: Tuyet doi khong cho phep don dep cac thu muc goc / cot loi
    # Bao ve truong hop bien moi truong bi rong hoac bi lech gia tri
    _DANGEROUS_ROOTS = set()
    for _d in [
        SYSDRIVE + "\\",
        WINDIR,
        USERPROFILE,
        os.environ.get("SystemRoot", "C:\\Windows"),
        "C:\\Users",
        "C:\\Windows\\System32",
        "C:\\Windows\\SysWOW64",
        "C:\\Program Files",
        "C:\\Program Files (x86)",
    ]:
        try:
            _DANGEROUS_ROOTS.add(Path(_d).resolve())
        except Exception:
            pass

    if p in _DANGEROUS_ROOTS:
        log(f"CHAN NGUY HIEM: Phat hien hanh vi co gang don dep thu muc goc nhay cam: {p}", "error")
        warn(f"Bi chặn: '{p}' nam trong danh sach thu muc bao ve. Khong thuc thi.")
        return 0, 0

    if not p.exists():
        return 0, 0

    # [PATCH v1] Bao ve Junction Point / Symlink
    if is_junction(str(p)):
        warn(f"Bo qua '{p}': la Junction Point / Reparse Point, khong xoa de bao ve du lieu goc.")
        return 0, 0
    freed = count = 0
    skipped_errors = []
    for root, dirs, files in os.walk(str(p), topdown=False):
        # Loc bo junction point con de tranh nhan vao ngoai pham vi
        dirs[:] = [d for d in dirs if not is_junction(os.path.join(root, d))]
        for fname in files:
            fp = os.path.join(root, fname)
            try:
                freed += os.path.getsize(fp)
                os.remove(fp)
                count += 1
            except PermissionError:
                skipped_errors.append(fp)
            except Exception as exc:
                skipped_errors.append(f"{fp} ({exc})")
        for d in dirs:
            dp = os.path.join(root, d)
            try:
                if not os.listdir(dp):
                    os.rmdir(dp)
            except Exception:
                pass
    # Bao cao ro rang thay vi nuot im
    if skipped_errors:
        log(f"_del_dir_contents: bo qua {len(skipped_errors)} file (bi khoa hoac khong du quyen): "
            f"{skipped_errors[:3]}{'...' if len(skipped_errors) > 3 else ''}", "warning")
    return freed, count

def _del_files_recursive(base: str, patterns=None, older_than_days=None):
    if not base or not os.path.exists(base):
        return 0, 0
    if is_junction(base):
        warn(f"Bo qua '{base}': la Junction Point / Reparse Point.")
        return 0, 0
    freed = count = 0
    skipped_errors = []
    now = time.time()
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if not is_junction(os.path.join(root, d))]
        for fname in files:
            if patterns:
                if not any(re.fullmatch(p.replace("*", ".*"), fname, re.IGNORECASE) for p in patterns):
                    continue
            fp = os.path.join(root, fname)
            try:
                if older_than_days:
                    age_days = (now - os.path.getmtime(fp)) / 86400
                    if age_days < older_than_days:
                        continue
                freed += os.path.getsize(fp)
                os.remove(fp)
                count += 1
            except PermissionError:
                skipped_errors.append(fp)
            except Exception as exc:
                skipped_errors.append(f"{fp} ({exc})")
    # [PATCH - Loi #6] Bao cao ro rang
    if skipped_errors:
        log(f"_del_files_recursive: bo qua {len(skipped_errors)} file: "
            f"{skipped_errors[:3]}{'...' if len(skipped_errors) > 3 else ''}", "warning")
    return freed, count

# =============================================================================
#  BACKUP / RESTORE JSON
# =============================================================================
def _default_backup() -> dict:
    return {
        "created_at":        datetime.now().isoformat(),
        "registry":          {},
        "notes":             [],
        "power": {
            "original_active_guid": None,
            "original_active_name": None,
            "created_schemes":      [],
        },
        "startup_registry":  [],
        "startup_shortcuts": [],
        "services":          {},
        "tasks":             [],
    }

def load_backup() -> dict:
    if not os.path.exists(BACKUP_JSON):
        return _default_backup()
    try:
        with open(BACKUP_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
        base = _default_backup()
        base.update(data or {})
        return base
    except json.JSONDecodeError as exc:
        log(f"load_backup: file backup bi hong (JSON invalid): {exc}. Dung gia tri mac dinh.", "warning")
        # Thu luu lai ban sao hu de debug
        try:
            broken = BACKUP_JSON + ".broken"
            shutil.copy2(BACKUP_JSON, broken)
            log(f"Da luu ban sao loi tai: {broken}", "info")
        except Exception:
            pass
        return _default_backup()
    except PermissionError as exc:
        log(f"load_backup: khong du quyen doc {BACKUP_JSON}: {exc}", "error")
        return _default_backup()
    except Exception as exc:
        log(f"load_backup: loi khong xac dinh: {exc}", "error")
        return _default_backup()

def save_backup(data: dict):
    ensure_dirs()
    # Ghi qua file tam truoc, sau do rename (atomic write) - tranh mat du lieu khi crash giua chung
    tmp = BACKUP_JSON + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        # atomic replace
        if os.path.exists(BACKUP_JSON):
            os.replace(tmp, BACKUP_JSON)
        else:
            os.rename(tmp, BACKUP_JSON)
    except PermissionError as exc:
        log(f"save_backup: khong du quyen ghi {BACKUP_JSON}: {exc}", "error")
    except Exception as exc:
        log(f"save_backup: loi ghi backup: {exc}", "error")
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass

def note(text: str):
    data = load_backup()
    data.setdefault("notes", []).append(
        f"{datetime.now().isoformat(timespec='seconds')} | {text}"
    )
    save_backup(data)

# =============================================================================
#  SYSTEM INFO  [PATCHED] Dung PowerShell CIM thay wmic (Win11 compatible)
#  wmic.exe da bi loai bo mac dinh tren Windows 11 build moi.
#  PowerShell Get-CimInstance la chuan thay the chinh thuc cua Microsoft.
# =============================================================================
def free_space_gb(path=None) -> float:
    """Tra ve dung luong trong (GB) cua partition chua path."""
    path = path or (SYSDRIVE + "\\")
    try:
        _, _, free = shutil.disk_usage(path)
        return round(free / (1 << 30), 1)
    except Exception:
        return 0.0

def total_space_gb(path=None) -> float:
    """Tra ve tong dung luong (GB) cua partition chua path."""
    path = path or (SYSDRIVE + "\\")
    try:
        total, _, _ = shutil.disk_usage(path)
        return round(total / (1 << 30), 1)
    except Exception:
        return 0.0

def get_os_caption_and_build():
    # Thu PowerShell truoc (Win8+), fallback wmic (Win7)
    if IS_WIN8_PLUS:
        ok_, out, _ = ps(
            "Get-CimInstance Win32_OperatingSystem | "
            "Select-Object Caption,Version,BuildNumber | ConvertTo-Json -Compress",
            timeout=15
        )
        if ok_ and out:
            try:
                d = json.loads(out)
                return (d.get("Caption") or f"{platform.system()} {platform.release()}",
                        d.get("Version") or "?",
                        str(d.get("BuildNumber") or WIN_BUILD))
            except Exception:
                pass
    # Fallback wmic (Win7 / loi PowerShell)
    caption = wmic_val("os get Caption",     "Caption")
    version = wmic_val("os get Version",     "Version")
    build   = wmic_val("os get BuildNumber", "BuildNumber")
    return (caption or f"{platform.system()} {platform.release()}",
            version or "?", build or str(WIN_BUILD))

def get_memory_gb():
    # Thu ctypes GlobalMemoryStatusEx truoc (khong can tien trinh con)
    try:
        import ctypes
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength",                ctypes.c_ulong),
                ("dwMemoryLoad",            ctypes.c_ulong),
                ("ullTotalPhys",            ctypes.c_ulonglong),
                ("ullAvailPhys",            ctypes.c_ulonglong),
                ("ullTotalPageFile",        ctypes.c_ulonglong),
                ("ullAvailPageFile",        ctypes.c_ulonglong),
                ("ullTotalVirtual",         ctypes.c_ulonglong),
                ("ullAvailVirtual",         ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]
        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        return round(stat.ullTotalPhys / (1 << 30), 1)
    except Exception:
        pass
    # Fallback PowerShell
    ok_, out, _ = ps(
        "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory", timeout=10
    )
    if ok_ and out.strip().isdigit():
        return round(int(out.strip()) / (1 << 30), 1)
    raw = wmic_val("computersystem get TotalPhysicalMemory", "TotalPhysicalMemory")
    try:
        return round(int(raw) / (1 << 30), 1)
    except Exception:
        return None

def has_battery() -> bool:
    if IS_WIN8_PLUS:
        ok_, out, _ = ps(
            "(Get-CimInstance Win32_Battery -ErrorAction SilentlyContinue).BatteryStatus",
            timeout=10
        )
        if ok_ and out.strip().isdigit() and int(out.strip()) > 0:
            return True
        return False
    raw = wmic("path Win32_Battery get BatteryStatus /value")
    for line in raw.splitlines():
        if "BatteryStatus=" in line:
            v = line.split("=", 1)[-1].strip()
            if v.isdigit() and int(v) > 0:
                return True
    return False

def on_ac_power():
    if IS_WIN8_PLUS:
        ok_, out, _ = ps(
            "(Get-CimInstance Win32_Battery -ErrorAction SilentlyContinue).BatteryStatus",
            timeout=10
        )
        if ok_ and out.strip().isdigit():
            try:
                return int(out.strip()) == 2
            except Exception:
                pass
        return None
    raw = wmic("path Win32_Battery get BatteryStatus /value")
    for line in raw.splitlines():
        if "BatteryStatus=" in line:
            v = line.split("=", 1)[-1].strip()
            try:
                return int(v) == 2
            except Exception:
                pass
    return None

def detect_fixed_drives():
    if IS_WIN8_PLUS:
        ok_, out, _ = ps(
            "Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | "
            "Select-Object -ExpandProperty DeviceID",
            timeout=15
        )
        if ok_ and out:
            drives = []
            for line in out.splitlines():
                letter = line.strip().strip(":").upper()
                if re.fullmatch(r"[A-Z]", letter):
                    drives.append(letter)
            if drives:
                return sorted(set(drives))
    raw = wmic("logicaldisk where DriveType=3 get DeviceID /value")
    drives = []
    for line in raw.splitlines():
        if "DeviceID=" in line:
            letter = line.split("=", 1)[-1].strip().strip(":").upper()
            if re.fullmatch(r"[A-Z]", letter):
                drives.append(letter)
    return sorted(set(drives)) if drives else ["C"]

def get_cpu_info() -> dict:
    """[PATCHED] PowerShell Get-CimInstance thay wmic, tuong thich Win11."""
    if IS_WIN8_PLUS:
        ok_, out, _ = ps(
            "Get-CimInstance Win32_Processor | "
            "Select-Object Name,NumberOfCores,NumberOfLogicalProcessors,MaxClockSpeed | "
            "ConvertTo-Json -Compress",
            timeout=15
        )
        if ok_ and out:
            try:
                d = json.loads(out)
                # Neu nhieu CPU, lay cai dau tien
                if isinstance(d, list):
                    d = d[0]
                return {
                    "Name":                      d.get("Name", "?"),
                    "NumberOfCores":             str(d.get("NumberOfCores", "?")),
                    "NumberOfLogicalProcessors": str(d.get("NumberOfLogicalProcessors", "?")),
                    "MaxClockSpeed":             str(d.get("MaxClockSpeed", "?")),
                }
            except Exception:
                pass
    # Fallback wmic (Win7)
    raw = wmic("cpu get Name,NumberOfCores,NumberOfLogicalProcessors,MaxClockSpeed /value")
    r = {}
    for line in raw.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            r[k.strip()] = v.strip()
    return r

def get_gpu_info() -> list:
    """[PATCHED] PowerShell Get-CimInstance thay wmic, tuong thich Win11."""
    if IS_WIN8_PLUS:
        ok_, out, _ = ps(
            "Get-CimInstance Win32_VideoController | "
            "Select-Object Name,DriverVersion,AdapterRAM | "
            "ConvertTo-Json -Compress",
            timeout=15
        )
        if ok_ and out:
            try:
                data = json.loads(out)
                if isinstance(data, dict):
                    data = [data]
                entries = []
                for item in data:
                    try:
                        vram_mb = int(item.get("AdapterRAM") or 0) // (1 << 20)
                    except Exception:
                        vram_mb = 0
                    entries.append({
                        "name":    item.get("Name", "?"),
                        "driver":  item.get("DriverVersion", "?"),
                        "vram_mb": vram_mb,
                    })
                return entries
            except Exception:
                pass
    # Fallback wmic (Win7)
    raw = wmic("path Win32_VideoController get Name,DriverVersion,AdapterRAM /value")
    entries, cur = [], {}
    for line in raw.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            cur[k.strip()] = v.strip()
            if "Name" in cur and "DriverVersion" in cur and "AdapterRAM" in cur:
                try:
                    vram_mb = int(cur.get("AdapterRAM", 0)) // (1 << 20)
                except Exception:
                    vram_mb = 0
                entries.append({
                    "name":    cur.get("Name", "?"),
                    "driver":  cur.get("DriverVersion", "?"),
                    "vram_mb": vram_mb,
                })
                cur = {}
    return entries

def get_full_sysinfo() -> dict:
    cpu   = get_cpu_info()
    gpus  = get_gpu_info()
    ram   = get_memory_gb()
    cap, ver, build = get_os_caption_and_build()
    return {
        "os_caption":   cap,
        "os_version":   ver,
        "os_build":     build,
        "python":       platform.python_version(),
        "ram_gb":       ram,
        "cpu_name":     cpu.get("Name", "?"),
        "cpu_cores":    cpu.get("NumberOfCores", "?"),
        "cpu_logical":  cpu.get("NumberOfLogicalProcessors", "?"),
        "cpu_mhz":      cpu.get("MaxClockSpeed", "?"),
        "gpus":         gpus,
        "has_battery":  has_battery(),
        "ac_power":     on_ac_power(),
        "free_c_gb":    free_space_gb(),
        "total_c_gb":   total_space_gb(),
        "drives":       detect_fixed_drives(),
    }

# =============================================================================
#  REGISTRY HELPERS  (su dung winreg native thay vi reg.exe – chong Injection,
#  nhanh hon ~100x, tuong thich Win7/10/11)
# =============================================================================
_HIVE_MAP = {
    "HKCU": winreg.HKEY_CURRENT_USER,
    "HKLM": winreg.HKEY_LOCAL_MACHINE,
    "HKCR": winreg.HKEY_CLASSES_ROOT,
    "HKU":  winreg.HKEY_USERS,
}

def reg_key_id(hive, path, name) -> str:
    return f"{hive}|{path}|{name}"

def reg_query(hive: str, path: str, name: str):
    """
    Tra ve (exists: bool, reg_type: int|None, value).
    Su dung winreg native – an toan, nhanh, khong sinh tien trinh con.
    """
    try:
        h_root = _HIVE_MAP.get(hive.upper())
        if h_root is None:
            return False, None, None
        with winreg.OpenKey(h_root, path, 0, winreg.KEY_READ) as key:
            val, reg_type = winreg.QueryValueEx(key, name)
            return True, reg_type, val
    except (FileNotFoundError, PermissionError):
        return False, None, None
    except Exception:
        return False, None, None

def reg_add(hive: str, path: str, name: str, value, regtype: int):
    """
    Ghi gia tri registry qua winreg native.
    Tra ve (ok: bool, stdout: str, stderr: str) de tuong thich voi code cu.
    """
    try:
        h_root = _HIVE_MAP.get(hive.upper())
        if h_root is None:
            return False, "", f"Hive khong hop le: {hive}"
        with winreg.CreateKeyEx(h_root, path, 0, winreg.KEY_SET_VALUE) as key:
            # [PATCHED v2] Ep kieu du lieu chinh xac:
            # int(value, 0) tu dong nhan dien ca thap phan ("10") lan hex ("0x0000000A")
            # Python se nem ValueError neu dung int("0x1") ma khong co base=0
            if regtype in (winreg.REG_DWORD, winreg.REG_QWORD):
                if isinstance(value, str):
                    write_val = int(value, 0)   # Ho tro "0x..." va "10" lan nhau
                else:
                    write_val = int(value)
            elif regtype in (winreg.REG_SZ, winreg.REG_EXPAND_SZ):
                write_val = str(value)
            else:
                write_val = value
            winreg.SetValueEx(key, name, 0, regtype, write_val)
        return True, "", ""
    except PermissionError as exc:
        return False, "", f"Khong du quyen: {exc}"
    except Exception as exc:
        return False, "", str(exc)

def reg_add_raw(hive: str, path: str, name: str, value, regtype_name):
    """
    Ghi registry voi ten kieu chuoi (VD: 'REG_DWORD').
    Tuong thich nguoc voi du lieu backup cu luu regtype duoi dang chuoi.
    """
    _NAME_TO_TYPE = {
        "REG_SZ":        winreg.REG_SZ,
        "REG_EXPAND_SZ": winreg.REG_EXPAND_SZ,
        "REG_DWORD":     winreg.REG_DWORD,
        "REG_QWORD":     winreg.REG_QWORD,
        "REG_BINARY":    winreg.REG_BINARY,
        "REG_MULTI_SZ":  winreg.REG_MULTI_SZ,
    }
    reg_type = _NAME_TO_TYPE.get(str(regtype_name).upper(), winreg.REG_SZ)
    return reg_add(hive, path, name, value, reg_type)

def reg_delete_value(hive: str, path: str, name: str):
    try:
        h_root = _HIVE_MAP.get(hive.upper())
        if h_root is None:
            return False, "", f"Hive khong hop le: {hive}"
        with winreg.OpenKey(h_root, path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, name)
        return True, "", ""
    except FileNotFoundError:
        return False, "", "Gia tri hoac khoa khong ton tai"
    except PermissionError as exc:
        return False, "", f"Khong du quyen: {exc}"
    except Exception as exc:
        return False, "", str(exc)

def reg_delete_key(hive: str, path: str):
    try:
        h_root = _HIVE_MAP.get(hive.upper())
        if h_root is None:
            return False, "", f"Hive khong hop le: {hive}"
        # winreg.DeleteKey chi xoa khoa rong; dung DeleteKeyEx cho khoa con
        parent, _, child = path.rpartition("\\")
        if not parent:
            return False, "", "Khong the xoa khoa goc"
        with winreg.OpenKey(h_root, parent, 0, winreg.KEY_ALL_ACCESS) as key:
            winreg.DeleteKey(key, child)
        return True, "", ""
    except FileNotFoundError:
        return False, "", "Khoa khong ton tai"
    except PermissionError as exc:
        return False, "", f"Khong du quyen: {exc}"
    except Exception as exc:
        return False, "", str(exc)

def backup_registry_values():
    data = load_backup()
    changed = 0
    for hive, path, name, exp_type in get_touched_registry():
        key = reg_key_id(hive, path, name)
        if key in data["registry"]:
            continue
        exists, cur_type_int, cur_val = reg_query(hive, path, name)
        # Luu ca int (cho winreg) lan ten chuoi (cho hien thi / tuong thich nguoc)
        cur_type_name = REG_TYPE_NAMES.get(cur_type_int, "REG_SZ") if cur_type_int is not None else None
        data["registry"][key] = {
            "hive": hive, "path": path, "name": name,
            "exists": exists,
            "reg_type":       cur_type_name,   # chuoi cho hien thi
            "reg_type_int":   cur_type_int,     # int cho winreg
            "value":          cur_val,
            "expected_type":  REG_TYPE_NAMES.get(exp_type, "REG_SZ"),
        }
        changed += 1
    save_backup(data)
    if changed:
        ok(f"Backup {changed} gia tri registry")

def restore_registry_values():
    data = load_backup()
    restored = kept = 0
    keep_dict = {}
    for key, item in data.get("registry", {}).items():
        hive, path, name = item["hive"], item["path"], item["name"]
        if item.get("exists"):
            ok_, _, _ = reg_add_raw(hive, path, name, item.get("value",""), item.get("reg_type","REG_SZ"))
        else:
            ok_, _, _ = reg_delete_value(hive, path, name)
        if ok_:
            restored += 1
        else:
            keep_dict[key] = item
            kept += 1
    data["registry"] = keep_dict
    save_backup(data)
    ok(f"Phuc hoi {restored} registry value | {kept} that bai")

# =============================================================================
#  RESTORE POINT
# =============================================================================
def create_restore_point():
    section("Tao Restore Point")
    cmd = (
        'Enable-ComputerRestore -Drive "C:\\" -ErrorAction SilentlyContinue; '
        'Checkpoint-Computer -Description "WinOptimizerUltimate_v5" '
        '-RestorePointType "MODIFY_SETTINGS" -ErrorAction Stop'
    )
    ok_, _, err_ = ps(cmd, timeout=180)
    if ok_:
        ok("Restore point da duoc tao thanh cong")
        return True
    # wmic fallback
    ok_, _, _ = run_cmd(
        ["wmic.exe", r"/Namespace:\\root\default", "Path", "SystemRestore",
         "Call", "CreateRestorePoint", "WinOptimizerUltimate", "100", "12"],
        shell=False, timeout=120
    )
    if ok_:
        ok("Restore point da duoc tao (wmic fallback)")
        return True
    warn("Khong tao duoc restore point – tinh nang co the bi tat tren may nay")
    return False

# =============================================================================
#  POWER SCHEME HELPERS
# =============================================================================
def list_power_schemes():
    ok_, out, _ = run_cmd(["powercfg","/list"], shell=False)
    result = []
    if not ok_:
        return result
    for line in out.splitlines():
        guid = extract_guid(line)
        if not guid:
            continue
        nm = re.search(r"\((.*?)\)", line)
        result.append({"guid": guid, "name": nm.group(1).strip() if nm else guid, "active": "*" in line})
    return result

def get_active_power_scheme():
    ok_, out, _ = run_cmd(["powercfg","/getactivescheme"], shell=False)
    if ok_:
        guid = extract_guid(out)
        nm   = re.search(r"\((.*?)\)", out)
        if guid:
            return guid, (nm.group(1).strip() if nm else guid)
    for s in list_power_schemes():
        if s["active"]:
            return s["guid"], s["name"]
    return None, None

def find_scheme_guid(preferred_names):
    schemes = list_power_schemes()
    for pref in [x.lower() for x in preferred_names]:
        for s in schemes:
            if pref in (s.get("name") or "").lower():
                return s["guid"], s["name"]
    return None, None

def scheme_exists(guid) -> bool:
    return any(s["guid"].lower() == (guid or "").lower() for s in list_power_schemes())

def duplicate_scheme(source_guid, new_name):
    ok_, out, err_ = run_cmd(["powercfg", "/duplicatescheme", str(source_guid)], shell=False)
    guid = extract_guid("\n".join(filter(None, [out, err_])))
    if not ok_ or not guid:
        err(f"Khong duplicate duoc power scheme: {err_ or out}")
        return None
    run_cmd(["powercfg", "/changename", str(guid), str(new_name), "WinOptimizer v5"], shell=False)
    return guid

def set_active_power_scheme(guid) -> bool:
    ok_, _, err_ = run_cmd(["powercfg", "/setactive", str(guid)], shell=False)
    if not ok_:
        err(f"Khong kich hoat duoc scheme {guid}: {err_}")
    return ok_

def _power_set(guid, ac_dc, subgroup, setting, value):
    action = "setacvalueindex" if ac_dc.upper() == "AC" else "setdcvalueindex"
    run_cmd(["powercfg", f"/{action}", str(guid), str(subgroup), str(setting), str(value)], shell=False)

def remember_original_power_once():
    data  = load_backup()
    power = data.setdefault("power", {})
    if power.get("original_active_guid"):
        return power["original_active_guid"], power.get("original_active_name")
    guid, name = get_active_power_scheme()
    power["original_active_guid"] = guid
    power["original_active_name"] = name
    save_backup(data)
    return guid, name

def get_created_scheme(profile_key):
    for item in load_backup().get("power", {}).get("created_schemes", []):
        if item.get("profile") == profile_key:
            return item.get("guid")
    return None

def remember_created_scheme(profile_key, guid, name):
    data  = load_backup()
    items = data.setdefault("power", {}).setdefault("created_schemes", [])
    items = [x for x in items if x.get("profile") != profile_key]
    items.append({"profile": profile_key, "guid": guid, "name": name})
    data["power"]["created_schemes"] = items
    save_backup(data)

def ensure_profile_scheme(profile_key, display_name):
    existing = get_created_scheme(profile_key)
    if existing and scheme_exists(existing):
        return existing
    remember_original_power_once()
    orig_guid, orig_name = get_active_power_scheme()
    data = load_backup()
    base_guid = data.get("power", {}).get("original_active_guid") or orig_guid
    base_name = data.get("power", {}).get("original_active_name") or orig_name
    if profile_key in ("gaming_plus", "competitive", "desktop_max"):
        g, n = find_scheme_guid(["Ultimate Performance", "High Performance"])
        if g:
            base_guid, base_name = g, n
    if not base_guid:
        err("Khong tim thay base power scheme")
        return None
    new_name = f"WinOpt v5 - {display_name}"
    guid = duplicate_scheme(base_guid, new_name)
    if guid:
        remember_created_scheme(profile_key, guid, new_name)
        note(f"Power scheme created: {new_name} ({guid})")
    return guid

def _apply_power_knobs(guid, knobs):
    """knobs = list of (ac_dc, subgroup, setting, value)"""
    for ac_dc, sub, setting, val in knobs:
        _power_set(guid, ac_dc, sub, setting, val)

def apply_power_profile(profile_key: str) -> bool:
    section("Power Profile")
    display_map = {
        "everyday":    "Everyday",
        "gaming_plus": "Gaming Plus",
        "competitive": "Competitive Extreme",
        "desktop_max": "Desktop Max Extreme",
        "laptop":      "Laptop Turbo",
    }
    guid = ensure_profile_scheme(profile_key, display_map.get(profile_key, profile_key))
    if not guid:
        return False
    if not set_active_power_scheme(guid):
        return False

    battery   = has_battery()
    ac_online = on_ac_power()

    BASE_GAMING_AC = [
        ("AC", "SUB_PROCESSOR", "PROCTHROTTLEMIN", 100),
        ("AC", "SUB_PROCESSOR", "PROCTHROTTLEMAX", 100),
        ("AC", "SUB_PROCESSOR", "PERFBOOSTMODE",   2),
    ]
    BASE_GAMING_DC = [
        ("DC", "SUB_PROCESSOR", "PROCTHROTTLEMIN", 5),
        ("DC", "SUB_PROCESSOR", "PROCTHROTTLEMAX", 85),
        ("DC", "SUB_PROCESSOR", "PERFBOOSTMODE",   1),
    ]
    WIN8_EXTRAS_EXTREME = [
        ("AC", "SUB_PROCESSOR", "CPMINCORES",       100),
        ("AC", "SUB_PROCESSOR", "CPMAXCORES",       100),
        ("AC", "SUB_PROCESSOR", "LATENCYHINTPERF",  100),
        ("AC", "SUB_PROCESSOR", "PERFINCTHRESHOLD",  5),
        ("AC", "SUB_PROCESSOR", "SYSCOOLPOL",         1),
        ("AC", "SUB_PROCESSOR", "SCHEDPOLICY",        1),
        ("AC", "SUB_PROCESSOR", "PERFEPP",            0),
    ]

    if profile_key == "everyday":
        knobs = [
            ("AC", "SUB_PROCESSOR", "PROCTHROTTLEMIN", 5),
            ("AC", "SUB_PROCESSOR", "PROCTHROTTLEMAX", 100),
            ("AC", "SUB_PROCESSOR", "PERFBOOSTMODE",   1),
            ("DC", "SUB_PROCESSOR", "PROCTHROTTLEMIN", 5),
            ("DC", "SUB_PROCESSOR", "PROCTHROTTLEMAX", 100),
            ("DC", "SUB_PROCESSOR", "PERFBOOSTMODE",   1),
        ]
    elif profile_key == "gaming_plus":
        if battery and ac_online is False:
            warn("May dang dung pin – nen cam sac truoc khi dung Gaming Plus.")
        knobs = BASE_GAMING_AC + BASE_GAMING_DC
        if IS_WIN8_PLUS:
            knobs += [
                ("AC", "SUB_PROCESSOR", "CPMINCORES",       100),
                ("AC", "SUB_PROCESSOR", "CPMAXCORES",       100),
                ("AC", "SUB_PROCESSOR", "LATENCYHINTPERF",  100),
                ("AC", "SUB_PROCESSOR", "PERFINCTHRESHOLD",  10),
                ("AC", "SUB_PROCESSOR", "SYSCOOLPOL",         1),
                ("AC", "SUB_PROCESSOR", "SCHEDPOLICY",        2),
                ("AC", "SUB_PROCESSOR", "PERFEPP",            0),
            ]
    elif profile_key in ("competitive", "desktop_max"):
        if battery and ac_online is False:
            warn("Profile nay rat ton dien – nen cam sac.")
        knobs = BASE_GAMING_AC + BASE_GAMING_DC
        if IS_WIN8_PLUS:
            knobs += WIN8_EXTRAS_EXTREME
        if profile_key == "desktop_max":
            knobs = [k if k[3] != 5 else ("AC","SUB_PROCESSOR","PERFINCTHRESHOLD",3) for k in knobs]
    elif profile_key == "laptop":
        knobs = [
            ("AC", "SUB_PROCESSOR", "PROCTHROTTLEMIN", 5),
            ("AC", "SUB_PROCESSOR", "PROCTHROTTLEMAX", 100),
            ("AC", "SUB_PROCESSOR", "PERFBOOSTMODE",   1),
            ("DC", "SUB_PROCESSOR", "PROCTHROTTLEMIN", 5),
            ("DC", "SUB_PROCESSOR", "PROCTHROTTLEMAX", 85),
            ("DC", "SUB_PROCESSOR", "PERFBOOSTMODE",   1),
        ]
        if IS_WIN8_PLUS:
            knobs += [
                ("AC", "SUB_PROCESSOR", "PERFINCTHRESHOLD", 15),
                ("AC", "SUB_PROCESSOR", "SYSCOOLPOL",        1),
                ("AC", "SUB_PROCESSOR", "PERFEPP",          25),
                ("DC", "SUB_PROCESSOR", "PERFEPP",          70),
            ]
    else:
        err(f"Profile '{profile_key}' khong hop le")
        return False

    _apply_power_knobs(guid, knobs)
    run_cmd(["powercfg", "/setactive", str(guid)], shell=False)
    ok(f"Da ap dung power profile: {display_map.get(profile_key, profile_key)}")
    return True

def restore_power_changes():
    data          = load_backup()
    power         = data.get("power", {})
    original_guid = power.get("original_active_guid")
    original_name = power.get("original_active_name")
    if original_guid and scheme_exists(original_guid):
        if set_active_power_scheme(original_guid):
            ok(f"Da chuyen lai power scheme goc: {original_name or original_guid}")
    else:
        run_cmd(["powercfg","/setactive","SCHEME_BALANCED"], shell=False)
        warn("Da chuyen ve Balanced (scheme goc khong con)")
    removed = 0
    for item in list(power.get("created_schemes", [])):
        g = item.get("guid")
        if g and scheme_exists(g):
            ok_, _, _ = run_cmd(["powercfg", "/delete", str(g)], shell=False)
            if ok_:
                removed += 1
    data.setdefault("power", {})["created_schemes"] = []
    save_backup(data)
    if removed:
        ok(f"Da xoa {removed} power scheme do script tao")

# =============================================================================
#  REGISTRY TUNING  (v5: them I/O, NTFS, AutoEndTasks, IRQ tweaks)
# =============================================================================
def optimize_gaming_registry():
    section("Gaming & Performance Registry Tweaks")
    backup_registry_values()

    base_items = [
        ("HKCU", r"Control Panel\Desktop",  "MenuShowDelay",        "20",       REG_SZ,    "MenuShowDelay = 20ms"),
        ("HKCU", r"Control Panel\Desktop",  "HungAppTimeout",       "1000",     REG_SZ,    "HungAppTimeout = 1000ms"),
        ("HKCU", r"Control Panel\Desktop",  "WaitToKillAppTimeout", "2000",     REG_SZ,    "WaitToKillAppTimeout = 2s"),
        ("HKCU", r"Control Panel\Desktop",  "AutoEndTasks",         "1",        REG_SZ,    "AutoEndTasks = ON"),
        ("HKLM", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile",
         "SystemResponsiveness",   10,          REG_DWORD, "MMCSS SystemResponsiveness = 10"),
        ("HKLM", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile",
         "NetworkThrottlingIndex", 0xffffffff,  REG_DWORD, "NetworkThrottlingIndex = max"),
        ("HKLM", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Games",
         "GPU Priority",        8,      REG_DWORD, "Games GPU Priority = 8"),
        ("HKLM", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Games",
         "Priority",            6,      REG_DWORD, "Games Priority = 6"),
        ("HKLM", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Games",
         "Scheduling Category", "High", REG_SZ,    "Scheduling Category = High"),
        ("HKLM", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Games",
         "SFIO Priority",       "High", REG_SZ,    "SFIO Priority = High"),
        # NEW v5: Process priority separation (foreground apps get more CPU slices)
        ("HKLM", r"SYSTEM\CurrentControlSet\Control\PriorityControl",
         "Win32PrioritySeparation", 38, REG_DWORD, "Win32PrioritySeparation = 38 (foreground boost)"),
        # NEW v5: NTFS last access timestamp OFF (giam ghi dia)
        ("HKLM", r"SYSTEM\CurrentControlSet\Control\FileSystem",
         "NtfsDisableLastAccessUpdate", 1, REG_DWORD, "NTFS LastAccessUpdate = OFF"),
        # NEW v5: NTFS paging
        ("HKLM", r"SYSTEM\CurrentControlSet\Control\FileSystem",
         "NtfsMemoryUsage", 2, REG_DWORD, "NTFS MemoryUsage = 2 (performance)"),
    ]

    win10_items = [
        ("HKCU", r"SOFTWARE\Microsoft\GameBar",  "AutoGameModeEnabled",    1, REG_DWORD, "Game Mode = ON"),
        ("HKCU", r"SOFTWARE\Microsoft\GameBar",  "AllowAutoGameMode",      1, REG_DWORD, "Allow Auto Game Mode = ON"),
        ("HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\GameDVR",
         "AppCaptureEnabled",    0, REG_DWORD, "Background capture = OFF"),
        ("HKCU", r"System\GameConfigStore",      "GameDVR_Enabled",        0, REG_DWORD, "Game DVR = OFF"),
        # NEW v5: tat Xbox overlay record limits
        ("HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\GameDVR",
         "MaximumRecordLength",  0, REG_DWORD, "Xbox record length = 0"),
    ]

    all_items = base_items + (win10_items if IS_WIN10_PLUS else [])
    done = total = 0
    for hive, path, name, value, regtype, label in all_items:
        total += 1
        ok_, _, _ = reg_add(hive, path, name, value, regtype)
        if ok_:
            ok(label)
            done += 1
        else:
            warn(f"Bo qua: {label}")
    info(f"Registry tweaks: {done}/{total} thanh cong")

def optimize_visuals():
    section("Visual Effects (Best Performance)")
    backup_registry_values()
    items = [
        ("HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\VisualEffects",
         "VisualFXSetting", 2, REG_DWORD, "Visual Effects = Best Performance"),
        ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced",
         "TaskbarAnimations", 0, REG_DWORD, "Taskbar animations = OFF"),
        ("HKCU", r"Control Panel\Desktop\WindowMetrics",
         "MinAnimate", "0", REG_SZ, "Window minimize/maximize animation = OFF"),
    ]
    if IS_WIN10_PLUS:
        items.append(("HKCU",
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            "EnableTransparency", 0, REG_DWORD, "Transparency = OFF"))
    for hive, path, name, value, regtype, label in items:
        ok_, _, _ = reg_add(hive, path, name, value, regtype)
        if ok_: ok(label)
        else:   warn(f"Bo qua: {label}")

def optimize_mouse():
    section("Mouse Input (Pointer Precision OFF)")
    backup_registry_values()
    for name, val, label in [
        ("MouseSpeed",      "0", "Enhance pointer precision = OFF"),
        ("MouseThreshold1", "0", "MouseThreshold1 = 0"),
        ("MouseThreshold2", "0", "MouseThreshold2 = 0"),
    ]:
        ok_, _, _ = reg_add("HKCU", r"Control Panel\Mouse", name, val, REG_SZ)
        if ok_: ok(label)
        else:   warn(f"Bo qua: {label}")

def optimize_low_latency_registry():
    section("Low-Latency Registry Tweaks")
    backup_registry_values()
    items = [
        ("HKLM", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile",
         "SystemResponsiveness",   10,          REG_DWORD, "SystemResponsiveness = 10"),
        ("HKLM", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile",
         "NetworkThrottlingIndex", 0xffffffff,  REG_DWORD, "NetworkThrottlingIndex = max"),
    ]
    for hive, path, name, value, regtype, label in items:
        ok_, _, _ = reg_add(hive, path, name, value, regtype)
        if ok_: ok(label)
        else:   warn(f"Bo qua: {label}")

def enable_hags():
    if not IS_WIN10_PLUS or WIN_BUILD < 19041:
        warn("HAGS chi ho tro Win10 build 2004+ (19041+). Bo qua.")
        return
    section("Hardware-Accelerated GPU Scheduling (HAGS)")
    backup_registry_values()
    ok_, _, _ = reg_add("HKLM", r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers",
                        "HwSchMode", 2, REG_DWORD)
    if ok_:
        ok("HAGS = ON (can restart, GPU/driver phai ho tro)")
    else:
        warn("Khong bat duoc HAGS")

# NEW v5: Disable Nagle's algorithm (giam latency mang game online)
def optimize_network_registry():
    section("Network Registry Tweaks (anti-Nagle, TCP)")
    backup_registry_values()
    # [PATCHED] Dung winreg native de enumerate interface keys
    # Tranh reg.exe shell=True va parse chuoi
    iface_base = r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces"
    iface_count = 0
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, iface_base, 0,
                            winreg.KEY_READ) as base_key:
            idx = 0
            while True:
                try:
                    sub_name = winreg.EnumKey(base_key, idx)
                    iface_path = f"{iface_base}\\{sub_name}"
                    reg_add("HKLM", iface_path, "TcpAckFrequency", 1, winreg.REG_DWORD)
                    reg_add("HKLM", iface_path, "TCPNoDelay",      1, winreg.REG_DWORD)
                    iface_count += 1
                    idx += 1
                except OSError:
                    break
    except PermissionError:
        warn("Khong du quyen de thay doi Tcpip Interface keys")
    ok(f"TcpAckFrequency=1, TCPNoDelay=1 cho {iface_count} interfaces")
    # TCP auto-tuning
    run_cmd(["netsh","int","tcp","set","global","autotuninglevel=normal"], shell=False)
    run_cmd(["netsh","int","tcp","set","global","congestionprovider=ctcp"], shell=False)
    ok("TCP AutoTuning=normal, CTCP enabled")

# =============================================================================
#  SERVICES  (sc.exe – Win7 + Win10)
# =============================================================================
def sc_query_state(name):
    ok_, out, _ = run_cmd(["sc", "query", name], shell=False, timeout=30)
    if not ok_:
        return None
    m = re.search(r"STATE\s*:\s*\d+\s+(\w+)", out, re.IGNORECASE)
    return m.group(1).lower() if m else None

def sc_query_start(name):
    ok_, out, _ = run_cmd(["sc", "qc", name], shell=False, timeout=30)
    if not ok_:
        return None
    m = re.search(r"START_TYPE\s*:\s*\d+\s+(\w+)", out, re.IGNORECASE)
    raw = (m.group(1).lower() if m else "")
    if "auto"     in raw: return "auto"
    if "demand"   in raw or "manual" in raw: return "demand"
    if "disabled" in raw: return "disabled"
    return raw

def sc_config_start(name, mode) -> bool:
    sc_mode = {"auto":"auto","automatic":"auto","manual":"demand","demand":"demand","disabled":"disabled"}.get((mode or "").lower(),"demand")
    ok_, _, _ = run_cmd(["sc","config",name,f"start= {sc_mode}"], shell=False, timeout=30)
    return ok_

def sc_stop(name) -> bool:
    ok_, _, _ = run_cmd(["net","stop",name,"/y"], shell=False, timeout=60)
    return ok_

def sc_start(name) -> bool:
    ok_, _, _ = run_cmd(["net","start",name], shell=False, timeout=60)
    return ok_

def backup_services_once(names):
    data  = load_backup()
    store = data.setdefault("services", {})
    changed = 0
    for name in names:
        if name in store:
            continue
        state      = sc_query_state(name)
        start_type = sc_query_start(name)
        store[name] = {"name": name, "state": state or "", "start_mode": start_type or "",
                       "exists": state is not None}
        changed += 1
    save_backup(data)
    if changed:
        ok(f"Backup {changed} service state")

def apply_service_trim(extreme=False):
    section("Service Trim" + (" (Extreme)" if extreme else " (Basic)"))
    names = list(get_low_risk_services())
    if extreme:
        for s in _EXTREME_SERVICES:
            if s not in names:
                names.append(s)
        warn("Extreme: tat them SysMain + WSearch.")
    backup_services_once(names)
    changed = skipped = 0
    for i, name in enumerate(names):
        _set_progress(int(i*100/len(names)), f"Tat: {name}")
        state = sc_query_state(name)
        if state is None:
            info(f"Khong tim thay: {name}")
            skipped += 1
            continue
        ok_mode = sc_config_start(name, "disabled")
        sc_stop(name)
        if ok_mode:
            ok(f"Disabled: {name}")
            changed += 1
        else:
            warn(f"Khong doi duoc: {name}")
    _set_progress(100, "Xong")
    _end_progress()
    note(f"Service trim ({'extreme' if extreme else 'basic'}): {changed} service")
    ok(f"Service trim xong: {changed} changed, {skipped} skip")

def restore_service_changes():
    section("Phuc Hoi Services")
    data     = load_backup()
    services = data.get("services", {})
    if not services:
        info("Khong co service backup")
        return
    kept = {}
    restored = 0
    for name, item in services.items():
        if not item.get("exists"):
            continue
        desired = item.get("start_mode", "demand")
        ok_mode = sc_config_start(name, desired)
        if desired != "disabled" and item.get("state","").lower() == "running":
            sc_start(name)
        if ok_mode:
            restored += 1
        else:
            kept[name] = item
    data["services"] = kept
    save_backup(data)
    ok(f"Phuc hoi {restored} service")

# =============================================================================
#  SCHEDULED TASKS  (schtasks.exe – Win7 + Win10)
# =============================================================================
def query_task_enabled(task_path, task_name):
    full = (task_path or "").rstrip("\\") + "\\" + task_name
    ok_, out, _ = run_cmd(["schtasks","/query","/tn",full,"/fo","LIST"], shell=False, timeout=30)
    if not ok_:
        return None
    for line in out.splitlines():
        if re.match(r"\s*Status\s*:", line, re.IGNORECASE):
            return "disabled" not in line.lower()
    return True

def schtask_change(task_path, task_name, enable=False) -> bool:
    full = (task_path or "").rstrip("\\") + "\\" + task_name
    flag = "/enable" if enable else "/disable"
    ok_, _, _ = run_cmd(["schtasks","/change","/tn",full,flag], shell=False, timeout=60)
    return ok_

def apply_task_trim():
    section("Scheduled Task Trim")
    changed = skipped = 0
    for i, (tp, tn) in enumerate(LOW_RISK_TASKS):
        _set_progress(int(i*100/len(LOW_RISK_TASKS)), tn)
        # backup
        data  = load_backup()
        items = data.setdefault("tasks", [])
        key   = f"{tp}|{tn}"
        if not any(f"{x.get('task_path','')}|{x.get('task_name','')}" == key for x in items):
            enabled = query_task_enabled(tp, tn)
            items.append({"task_path":tp,"task_name":tn,"enabled":enabled,"exists":enabled is not None})
            save_backup(data)
        # disable
        enabled = query_task_enabled(tp, tn)
        if enabled is None:
            skipped += 1
            continue
        if not enabled:
            skipped += 1
            continue
        if schtask_change(tp, tn, enable=False):
            ok(f"Disabled task: {tn}")
            changed += 1
        else:
            warn(f"Khong disable duoc: {tn}")
    _set_progress(100,"Xong")
    _end_progress()
    note(f"Task trim: {changed} disabled")
    ok(f"Task trim xong: {changed} changed, {skipped} skip")

def restore_task_changes():
    section("Phuc Hoi Scheduled Tasks")
    data  = load_backup()
    items = data.get("tasks", [])
    kept  = []
    restored = 0
    for item in items:
        if not item.get("exists"):
            continue
        if schtask_change(item["task_path"], item["task_name"], enable=bool(item.get("enabled"))):
            restored += 1
        else:
            kept.append(item)
    data["tasks"] = kept
    save_backup(data)
    ok(f"Phuc hoi {restored} task")

# =============================================================================
#  CLEANER MODULES
# =============================================================================
class CleanResult:
    """Theo doi ket qua don dep."""
    def __init__(self, module_name: str):
        self.name    = module_name
        self.freed   = 0
        self.deleted = 0
        self.entries = []

    def add(self, label: str, freed: int, deleted: int):
        self.freed   += freed
        self.deleted += deleted
        if freed:
            self.entries.append((label, freed, deleted))
            ok(f"{label}: {fmt_bytes(freed)} / {deleted} files")

    def summary(self) -> str:
        return f"{self.name}: {fmt_bytes(self.freed)} giai phong, {self.deleted} files"

def _clean(result: CleanResult, path: str, label: str, patterns=None, days=None):
    if patterns or days:
        f, d = _del_files_recursive(path, patterns=patterns, older_than_days=days)
    else:
        f, d = _del_dir_contents(path)
    result.add(label, f, d)

# ─── Temp files ─────────────────────────────────────────────────────────────
def cleanup_temp_files() -> CleanResult:
    section("Temp & Prefetch Cleanup")
    r = CleanResult("Temp")
    seen = set()
    for d in TEMP_DIRS:
        if not d:
            continue
        key = d.lower()
        if key in seen:
            continue
        seen.add(key)
        _clean(r, d, os.path.basename(d) or d)
    run_cmd(["ipconfig", "/flushdns"], shell=False)
    ok(r.summary())
    return r

# ─── Browser cache ──────────────────────────────────────────────────────────
def _check_running_processes(*exe_names: str) -> list:
    """
    Kiem tra xem cac tien trinh co dang chay khong (khong sinh tien trinh con).
    Tra ve list ten tien trinh dang chay trong exe_names.
    """
    running = []
    try:
        ok_, out, _ = run_cmd(["tasklist", "/FO", "CSV", "/NH"], shell=False, timeout=10)
        if ok_:
            for row in csv.reader(io.StringIO(out)):
                if not row:
                    continue
                name = row[0].strip('"').lower()
                for exe in exe_names:
                    if name == exe.lower() and exe.lower() not in running:
                        running.append(exe)
    except Exception:
        pass
    return running

def cleanup_browser_cache() -> CleanResult:
    section("Browser Cache Cleanup")
    r = CleanResult("Browser")
    # [PATCHED v3] Kiem tra tien trinh truoc khi don dep - canh bao nguoi dung
    browser_procs = _check_running_processes(
        "chrome.exe", "msedge.exe", "brave.exe", "opera.exe",
        "vivaldi.exe", "firefox.exe", "iexplore.exe"
    )
    if browser_procs:
        warn(f"CANH BAO: Cac trinh duyet sau dang chay: {', '.join(browser_procs)}. "
             f"Mot so cache co the bi khoa va khong the xoa sach hoan toan. "
             f"Hay dong trinh duyet truoc khi chay chuc nang nay de dat hieu qua toi da.")
    if LOCALAPPDATA:
        for sub, label in [
            (r"Google\Chrome\User Data\Default\Cache",         "Chrome Cache"),
            (r"Google\Chrome\User Data\Default\Code Cache",    "Chrome Code Cache"),
            (r"Google\Chrome\User Data\Default\GPUCache",      "Chrome GPU Cache"),
            (r"BraveSoftware\Brave-Browser\User Data\Default\Cache", "Brave Cache"),
            (r"Opera Software\Opera Stable\Cache",             "Opera Cache"),
            (r"Vivaldi\User Data\Default\Cache",               "Vivaldi Cache"),
            (r"Microsoft\Windows\INetCache",                   "IE/Edge INetCache"),
            (r"Microsoft\Windows\WebCache",                    "WebCache"),
            (r"Microsoft\Windows\Temporary Internet Files",    "IE Temp Files"),
        ]:
            _clean(r, os.path.join(LOCALAPPDATA, sub), label)
        if IS_WIN10_PLUS:
            for sub, label in [
                (r"Microsoft\Edge\User Data\Default\Cache",      "Edge Cache"),
                (r"Microsoft\Edge\User Data\Default\Code Cache", "Edge Code Cache"),
            ]:
                _clean(r, os.path.join(LOCALAPPDATA, sub), label)
    # Firefox
    if APPDATA:
        ff_profiles = os.path.join(APPDATA, r"Mozilla\Firefox\Profiles")
        if os.path.isdir(ff_profiles):
            for prof in os.listdir(ff_profiles):
                pp = os.path.join(ff_profiles, prof)
                if os.path.isdir(pp):
                    _clean(r, os.path.join(pp, "cache2"), f"Firefox cache2 ({prof[:8]})")
                    _clean(r, os.path.join(pp, "thumbnails"), f"Firefox thumbs ({prof[:8]})")
    ok(r.summary())
    return r

# ─── Game cache ─────────────────────────────────────────────────────────────
def cleanup_game_cache() -> CleanResult:
    section("Game Launcher Cache Cleanup")
    r = CleanResult("Game")
    prog86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    for path, label in [
        (os.path.join(prog86, r"Steam\appcache"),           "Steam appcache"),
        (os.path.join(prog86, r"Steam\depotcache"),         "Steam depotcache"),
        (os.path.join(prog86, r"Steam\logs"),               "Steam logs"),
        (os.path.join(prog86, r"Origin\Cache"),             "Origin Cache"),
        (os.path.join(prog86, r"Ubisoft\Ubisoft Game Launcher\cache"), "Ubisoft Cache"),
    ]:
        _clean(r, path, label)
    if LOCALAPPDATA:
        for sub, label in [
            (r"EpicGamesLauncher\Saved\Logs",     "Epic Logs"),
            (r"EpicGamesLauncher\Saved\webcache", "Epic WebCache"),
        ]:
            _clean(r, os.path.join(LOCALAPPDATA, sub), label)
    if APPDATA:
        _clean(r, os.path.join(APPDATA, r"GOG.com\Galaxy\logs"), "GOG Galaxy Logs")
    ok(r.summary())
    return r

# ─── Office & app cache ──────────────────────────────────────────────────────
def cleanup_office_and_apps() -> CleanResult:
    section("Office & App Cache Cleanup")
    r = CleanResult("Office")
    # [PATCHED v3] Kiem tra tien trinh truoc khi don dep
    office_procs = _check_running_processes(
        "WINWORD.EXE", "EXCEL.EXE", "POWERPNT.EXE", "OUTLOOK.EXE",
        "ONENOTE.EXE", "AcroRd32.exe", "Acrobat.exe",
        "Discord.exe", "Spotify.exe", "Zoom.exe", "slack.exe"
    )
    if office_procs:
        warn(f"CANH BAO: Cac ung dung sau dang chay: {', '.join(office_procs)}. "
             f"File cache co the bi khoa. Hay dong ung dung truoc de don dep hieu qua hon.")
    if APPDATA:
        for sub, label in [
            (r"Microsoft\Office\Recent",                "Office Recent Files"),
            (r"Microsoft\Office\16.0\OfficeFileCache",  "Office 2016+ FileCache"),
            (r"Microsoft\Office\15.0\OfficeFileCache",  "Office 2013 FileCache"),
        ]:
            _clean(r, os.path.join(APPDATA, sub), label)
        for app in ["Adobe","Discord","Spotify","Zoom","Slack","Oracle","Java","Skype"]:
            p = os.path.join(APPDATA, app)
            if os.path.isdir(p):
                f, d = _del_files_recursive(p, patterns=["*.log","*.tmp","*.temp"])
                r.add(f"{app} (Roaming)", f, d)
    if LOCALAPPDATA:
        for app in ["Adobe","Discord","Spotify","Zoom","Slack","Oracle","Java","Skype"]:
            p = os.path.join(LOCALAPPDATA, app)
            if os.path.isdir(p):
                f, d = _del_files_recursive(p, patterns=["*.log","*.tmp","*.temp"])
                r.add(f"{app} (Local)", f, d)
    ok(r.summary())
    return r

# ─── Dev tools cache ─────────────────────────────────────────────────────────
def cleanup_dev_tools() -> CleanResult:
    section("Developer Tools Cache Cleanup")
    r = CleanResult("DevTools")
    home = USERPROFILE or os.path.expanduser("~")
    for sub, label in [
        (r".android\cache",  "Android Studio cache"),
        (r".gradle\caches",  "Gradle caches"),
        (r".docker\tmp",     "Docker tmp"),
        (r".npm\_logs",      "npm logs"),
        (r".node-gyp",       "node-gyp"),
    ]:
        _clean(r, os.path.join(home, sub), label)
    if APPDATA:
        _clean(r, os.path.join(APPDATA, r"Code\logs"), "VS Code logs")
    # __pycache__
    pycache_count = 0
    for root, dirs, _ in os.walk(home):
        for d in dirs:
            if d == "__pycache__":
                dp = os.path.join(root, d)
                f, n = _del_dir_contents(dp)
                r.freed   += f
                r.deleted += n
                try:
                    os.rmdir(dp)
                    pycache_count += 1
                except Exception:
                    pass
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules", ".svn")]
    if pycache_count:
        info(f"Da xoa {pycache_count} thu muc __pycache__")
    ok(r.summary())
    return r

# ─── Windows Store ───────────────────────────────────────────────────────────
def cleanup_store_cache() -> CleanResult:
    r = CleanResult("Store")
    if not IS_WIN10_PLUS:
        info("Windows Store khong co tren Win7. Bo qua.")
        return r
    section("Windows Store Cache Cleanup")
    run_cmd(["wsreset.exe"], shell=False, timeout=60)
    if LOCALAPPDATA:
        packages = os.path.join(LOCALAPPDATA, "Packages")
        if os.path.isdir(packages):
            for pkg in os.listdir(packages):
                if "WindowsStore" in pkg or "StorePurchaseApp" in pkg:
                    _clean(r, os.path.join(packages, pkg, "LocalCache"), f"Store {pkg[:25]}")
    ok(r.summary())
    return r

# ─── System files ─────────────────────────────────────────────────────────────
def cleanup_system_files() -> CleanResult:
    section("System Files Cleanup")
    r = CleanResult("SystemFiles")
    # Windows.old
    win_old = os.path.join(SYSDRIVE + "\\", "Windows.old")
    _clean(r, win_old, "Windows.old")
    # Memory dumps
    for dp in [os.path.join(WINDIR,"MEMORY.DMP"), os.path.join(WINDIR,"Minidump")]:
        if os.path.isfile(dp):
            try:
                r.freed += os.path.getsize(dp)
                os.remove(dp)
                r.deleted += 1
                ok(f"Xoa: {dp}")
            except Exception:
                pass
        elif os.path.isdir(dp):
            f, d = _del_files_recursive(dp, patterns=["*.dmp"])
            r.add("Minidump", f, d)
    # WER reports >30 days
    f, d = _del_files_recursive(
        os.path.join(PROGRAM_DATA, r"Microsoft\Windows\WER\ReportArchive"),
        older_than_days=30
    )
    r.add("WER Reports (>30d)", f, d)
    # Old log files >30 days
    for log_d in [os.path.join(WINDIR,"Logs"), os.path.join(WINDIR,r"System32\LogFiles")]:
        f, d = _del_files_recursive(log_d, patterns=["*.log","*.etl"], older_than_days=30)
        r.add(f"Logs ({os.path.basename(log_d)})", f, d)
    # NEW v5: Event log backup files
    f, d = _del_files_recursive(os.path.join(WINDIR, r"System32\winevt\Logs"),
                                 patterns=["*.evtx_bak","*.evtx.old"])
    r.add("Event Log backups", f, d)
    ok(r.summary())
    return r

# ─── Security & Privacy ───────────────────────────────────────────────────────
def cleanup_security_privacy() -> CleanResult:
    section("Security & Privacy Cleanup")
    r = CleanResult("Privacy")
    if LOCALAPPDATA:
        _clean(r, os.path.join(LOCALAPPDATA, r"Microsoft\Windows\History"), "Shell History")
    if APPDATA:
        _clean(r, os.path.join(APPDATA, r"Microsoft\Windows\Recent"), "Recent Files")
    # Registry history
    for hive, path in [
        ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Explorer\RunMRU"),
        ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Explorer\TypedPaths"),
        ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Explorer\WordWheelQuery"),
        ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Explorer\RecentDocs"),
        ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Explorer\Map Network Drive MRU"),
    ]:
        ok_, _, _ = reg_delete_key(hive, path)
        if ok_:
            ok(f"Xoa registry: {path.split(chr(92))[-1]}")
    ok(r.summary())
    return r

# ─── Recycle Bin + Thumbnails ─────────────────────────────────────────────────
def cleanup_recycle_and_thumbs() -> CleanResult:
    section("Recycle Bin & Thumbnail Cache")
    r = CleanResult("Recycle")
    for drive in detect_fixed_drives():
        for rb_name in ["$Recycle.bin", "RECYCLER"]:
            _clean(r, f"{drive}:\\{rb_name}", f"Recycle {drive}:")
    if LOCALAPPDATA:
        f, d = _del_files_recursive(
            os.path.join(LOCALAPPDATA, r"Microsoft\Windows\Explorer"),
            patterns=["thumbcache_*.db","iconcache_*.db"]
        )
        r.add("Thumbnail cache", f, d)
    # NEW v5: Font cache
    f, d = _del_files_recursive(
        os.path.join(LOCALAPPDATA or "", r"Microsoft\Windows\Fonts"),
        patterns=["*.tmp"]
    )
    r.add("Font cache tmp", f, d)
    ok(r.summary())
    return r

# ─── Old Downloads ────────────────────────────────────────────────────────────
def cleanup_old_downloads(older_than_days=30) -> CleanResult:
    section(f"Old Downloads Cleanup (> {older_than_days} days)")
    r = CleanResult("Downloads")
    dl = os.path.join(USERPROFILE, "Downloads")
    f, d = _del_files_recursive(dl, older_than_days=older_than_days)
    r.add("Downloads", f, d)
    ok(r.summary())
    return r

# ─── Network optimization ─────────────────────────────────────────────────────
def optimize_network():
    section("Network Optimization")
    run_cmd(["ipconfig", "/flushdns"], shell=False); ok("DNS cache flushed")
    run_cmd(["ipconfig", "/registerdns"], shell=False); ok("DNS re-registered")
    run_cmd(["netsh","int","ip","reset"], shell=False, timeout=60); ok("TCP/IP stack reset")
    run_cmd(["netsh","winsock","reset"], shell=False, timeout=60); ok("Winsock reset (can restart)")
    run_cmd(["arp","-d","*"], shell=False); ok("ARP cache cleared")

# ─── Drive optimization ───────────────────────────────────────────────────────
def optimize_drives():
    section("Drive Optimization")
    drives = detect_fixed_drives()
    for drive in drives:
        cmd = (["defrag", f"{drive}:", "/O", "/U"] if IS_WIN8_PLUS
               else ["defrag", f"{drive}:", "/U", "/V"])
        ok_, _, err_ = run_cmd(cmd, timeout=1200, shell=False)
        if ok_: ok(f"Drive {drive}: optimized")
        else:   warn(f"Drive {drive}: {err_ or 'loi'}")

# ─── DISM & SFC ───────────────────────────────────────────────────────────────
def run_component_cleanup():
    if not IS_WIN8_PLUS:
        info("DISM chi ho tro Win8+. Bo qua.")
        return
    section("DISM Component Store Cleanup")
    ok_, out, err_ = run_cmd(
        ["Dism.exe", "/Online", "/Cleanup-Image", "/StartComponentCleanup"],
        timeout=3600, shell=False
    )
    if ok_: ok("DISM StartComponentCleanup xong")
    else:   warn(err_ or out or "That bai")

def run_sfc():
    section("System File Checker")
    info("Chay sfc /scannow ... (co the mat vai phut)")
    ok_, out, err_ = run_cmd(["sfc","/scannow"], timeout=5400, shell=False)
    if ok_: ok("SFC hoan thanh")
    else:   warn(err_ or out or "SFC that bai")

def run_dism_restore():
    if not IS_WIN8_PLUS:
        info("DISM RestoreHealth chi ho tro Win8+. Bo qua.")
        return
    section("DISM RestoreHealth")
    info("Chay Dism /RestoreHealth ... (co the mat 15-30 phut)")
    ok_, out, err_ = run_cmd(
        ["Dism", "/Online", "/Cleanup-Image", "/RestoreHealth"],
        timeout=7200, shell=False
    )
    if ok_: ok("DISM RestoreHealth xong")
    else:   warn(err_ or out or "That bai")

# =============================================================================
#  STARTUP MANAGER
# =============================================================================
def enumerate_startup_entries():
    items = []
    for hive, path in RUN_REG_PATHS:
        ok_, out, _ = run_cmd(["reg","query",f"{hive}\\{path}"], shell=False)
        if ok_:
            pattern = re.compile(r"^\s*(.+?)\s+(REG_[A-Z0-9_]+)\s+(.*)$")
            for line in out.splitlines():
                if line.upper().startswith("HKEY_"): continue
                m = pattern.match(line.rstrip())
                if m:
                    items.append({"kind":"reg","name":m.group(1).strip(),
                                   "hive":hive,"path":path,"reg_type":m.group(2).strip(),
                                   "value":m.group(3).strip(),"source":f"{hive}\\{path}"})
    for folder in STARTUP_FOLDERS:
        if folder and os.path.isdir(folder):
            for name in sorted(os.listdir(folder)):
                full = os.path.join(folder, name)
                if os.path.isfile(full):
                    items.append({"kind":"file","name":name,"full_path":full,"source":folder})
    return sorted(items, key=lambda x: (x["kind"], x["name"].lower()))

def disable_startup_item(item: dict, data: dict) -> bool:
    if item["kind"] == "reg":
        exists, reg_type, reg_val = reg_query(item["hive"], item["path"], item["name"])
        if not exists:
            return False
        data.setdefault("startup_registry",[]).append({
            "hive":item["hive"],"path":item["path"],"name":item["name"],
            "reg_type":reg_type,"value":reg_val
        })
        ok_, _, _ = reg_delete_value(item["hive"], item["path"], item["name"])
        return ok_
    else:
        if not os.path.exists(item["full_path"]):
            return False
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest  = os.path.join(DISABLED_STARTUP_DIR, f"{stamp}_{sanitize_filename(item['name'])}")
        try:
            shutil.move(item["full_path"], dest)
            data.setdefault("startup_shortcuts",[]).append({
                "original_path":item["full_path"],"backup_path":dest,"name":item["name"]
            })
            return True
        except Exception:
            return False

def restore_startup_items():
    section("Phuc Hoi Startup Items")
    data = load_backup()
    restored = 0
    kept_reg = []
    for item in data.get("startup_registry", []):
        ok_, _, _ = reg_add_raw(item["hive"],item["path"],item["name"],item["value"],item["reg_type"])
        if ok_: restored += 1
        else:   kept_reg.append(item)
    data["startup_registry"] = kept_reg
    kept_files = []
    for item in data.get("startup_shortcuts", []):
        src = item.get("backup_path")
        dst = item.get("original_path")
        try:
            if src and os.path.exists(src):
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.move(src, dst)
                restored += 1
            else:
                kept_files.append(item)
        except Exception:
            kept_files.append(item)
    data["startup_shortcuts"] = kept_files
    save_backup(data)
    ok(f"Phuc hoi {restored} startup items")

# =============================================================================
#  GAME PREP
# =============================================================================
def game_prep():
    section("Game Prep – Close Background Apps")
    warn("Hay luu cong viec truoc khi dong app.")
    ok_, out, _ = run_cmd(["tasklist","/FO","CSV","/NH"], shell=False, timeout=30)
    if not ok_:
        err("Khong lay duoc danh sach process")
        return
    running = set()
    for row in csv.reader(io.StringIO(out)):
        if row:
            running.add(row[0].strip('"').lower())
    found = [(exe, label) for exe, label in GAME_PREP_CANDIDATES if exe.lower() in running]
    if not found:
        info("Khong tim thay app nen nao dang chay.")
        return
    return found  # GUI will handle selection

def _kill_processes(found: list):
    closed = 0
    for exe, label in found:
        ok_, _, _ = run_cmd(["taskkill","/IM",exe,"/F"], shell=False, timeout=30)
        if ok_:
            ok(f"Dong: {label}")
            closed += 1
        else:
            warn(f"Khong dong duoc: {label}")
    ok(f"Game Prep: dong {closed} app")

# =============================================================================
#  WINDOWS TASK SCHEDULER – AUTO CLEAN SCHEDULE  (NEW v5)
# =============================================================================
def schedule_auto_clean(time_str: str = "03:00", task_name: str = "WinOptimizerUltimate_AutoClean") -> bool:
    """Len lich chay Full Cleaner hang ngay luc time_str (HH:MM)."""
    section(f"Len lich tu dong: {time_str} hang ngay")
    # Validate time_str truoc khi truyen vao lenh
    if not re.match(r"^\d{2}:\d{2}$", time_str):
        err(f"Dinh dang thoi gian khong hop le: {time_str}. Yeu cau HH:MM.")
        return False
    script_path = os.path.abspath(sys.argv[0])
    python_exe  = sys.executable
    # [PATCHED] Dung list args thay vi f-string shell=True
    # Tranh injection qua task_name hoac script_path co ky tu dac biet
    tr_value = f'"{python_exe}" "{script_path}" --auto-clean'
    ok_, out, err_ = run_cmd(
        ["schtasks", "/create",
         "/tn", task_name,
         "/tr", tr_value,
         "/sc", "DAILY",
         "/st", time_str,
         "/ru", "SYSTEM",
         "/f"],
        shell=False, timeout=60
    )
    if ok_:
        ok(f"Da tao task: {task_name} – chay luc {time_str} moi ngay")
        note(f"Scheduled auto-clean at {time_str} daily")
        return True
    else:
        err(f"Khong tao duoc task: {err_ or out}")
        return False

def remove_schedule(task_name: str = "WinOptimizerUltimate_AutoClean") -> bool:
    ok_, _, err_ = run_cmd(["schtasks", "/delete", "/tn", str(task_name), "/f"], shell=False, timeout=30)
    if ok_:
        ok(f"Da xoa task: {task_name}")
        return True
    else:
        warn(f"Khong xoa duoc task (co the chua ton tai): {err_}")
        return False

def check_schedule_exists(task_name: str = "WinOptimizerUltimate_AutoClean") -> bool:
    ok_, _, _ = run_cmd(["schtasks", "/query", "/tn", str(task_name)], shell=False, timeout=15)
    return ok_

# =============================================================================
#  HTML REPORT GENERATOR  (NEW v5)
# =============================================================================
def generate_html_report(results: list, sysinfo: dict, duration_s: float, profile_name: str = "") -> str:
    ts      = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ts_safe = datetime.now().strftime("%Y%m%d_%H%M%S")
    total_freed   = sum(r.freed   for r in results if hasattr(r, "freed"))
    total_deleted = sum(r.deleted for r in results if hasattr(r, "freed"))

    rows = ""
    for r in results:
        if not hasattr(r, "freed"): continue
        rows += f"<tr><td>{r.name}</td><td>{fmt_bytes(r.freed)}</td><td>{r.deleted}</td></tr>\n"

    gpus_html = "".join(
        f"<li>{g['name']} | Driver {g['driver']} | VRAM {g['vram_mb']} MB</li>"
        for g in sysinfo.get("gpus", [])
    )
    html = textwrap.dedent(f"""
    <!DOCTYPE html>
    <html lang="vi">
    <head>
    <meta charset="UTF-8">
    <title>{APP_NAME} – Bao Cao {ts}</title>
    <style>
      body{{font-family:Segoe UI,Arial,sans-serif;background:#1a1a2e;color:#eee;margin:0;padding:20px}}
      h1{{color:#00d4ff;border-bottom:2px solid #00d4ff;padding-bottom:8px}}
      h2{{color:#a78bfa;margin-top:28px}}
      table{{border-collapse:collapse;width:100%;margin-top:10px}}
      th{{background:#16213e;color:#00d4ff;padding:10px;text-align:left}}
      td{{padding:8px 10px;border-bottom:1px solid #2a2a4a}}
      tr:hover td{{background:#16213e}}
      .badge{{display:inline-block;padding:4px 12px;border-radius:20px;font-weight:bold}}
      .green{{background:#065f46;color:#6ee7b7}} .blue{{background:#1e3a5f;color:#93c5fd}}
      .card{{background:#16213e;border-radius:10px;padding:16px;margin-bottom:16px}}
      .big{{font-size:2.2em;font-weight:bold;color:#00d4ff}}
      ul{{padding-left:18px}} li{{margin:4px 0}}
    </style>
    </head>
    <body>
    <h1>🖥 {APP_NAME} <small style="font-size:.5em;color:#a78bfa">{APP_SUBTITLE}</small></h1>
    <p>Thoi gian: <b>{ts}</b> &nbsp;|&nbsp; Thoi luong: <b>{duration_s:.1f}s</b>
       {'&nbsp;|&nbsp; Profile: <b>' + profile_name + '</b>' if profile_name else ''}</p>

    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px">
      <div class="card"><div>Dung luong giai phong</div><div class="big">{fmt_bytes(total_freed)}</div></div>
      <div class="card"><div>Files da xoa</div><div class="big">{total_deleted:,}</div></div>
      <div class="card"><div>O C: con trong</div><div class="big">{sysinfo.get("free_c_gb",0)} GB</div></div>
    </div>

    <h2>Chi Tiet Don Dep</h2>
    <table>
      <tr><th>Module</th><th>Giai Phong</th><th>Files Xoa</th></tr>
      {rows}
    </table>

    <h2>Thong Tin He Thong</h2>
    <div class="card">
      <ul>
        <li><b>OS:</b> {sysinfo.get("os_caption","?")} | Build {sysinfo.get("os_build","?")}</li>
        <li><b>Python:</b> {sysinfo.get("python","?")}</li>
        <li><b>RAM:</b> {sysinfo.get("ram_gb","?")} GB</li>
        <li><b>CPU:</b> {sysinfo.get("cpu_name","?")} | {sysinfo.get("cpu_cores","?")} cores / {sysinfo.get("cpu_logical","?")} logical @ {sysinfo.get("cpu_mhz","?")} MHz</li>
        <li><b>GPU:</b><ul>{gpus_html}</ul></li>
        <li><b>O C: tong:</b> {sysinfo.get("total_c_gb",0)} GB | Con trong: {sysinfo.get("free_c_gb",0)} GB</li>
        <li><b>Nguon:</b> {'Pin' if sysinfo.get('has_battery') else 'May ban'} | {'AC' if sysinfo.get('ac_power') else 'DC/Unknown'}</li>
      </ul>
    </div>
    <p style="color:#555;font-size:.8em">Bao cao tao boi {APP_NAME} v{APP_VERSION}</p>
    </body></html>
    """).strip()

    path = os.path.join(REPORT_DIR, f"report_{ts_safe}.html")
    os.makedirs(REPORT_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    ok(f"Bao cao HTML: {path}")
    return path

# =============================================================================
#  HIGH-LEVEL PROFILES
# =============================================================================
def _run_full_clean(s: dict) -> list:
    """Chay tat ca module cleaner theo settings. Tra ve list CleanResult."""
    results = []
    modules = [
        ("clean_temp",         cleanup_temp_files,       "Temp"),
        ("clean_browser",      cleanup_browser_cache,    "Browser"),
        ("clean_game",         cleanup_game_cache,       "Game"),
        ("clean_office",       cleanup_office_and_apps,  "Office"),
        ("clean_devtools",     cleanup_dev_tools,        "DevTools"),
        ("clean_system_files", cleanup_system_files,     "System"),
        ("clean_recycle",      cleanup_recycle_and_thumbs, "Recycle"),
        ("clean_security",     cleanup_security_privacy, "Privacy"),
    ]
    if IS_WIN10_PLUS:
        modules.append(("clean_store", cleanup_store_cache, "Store"))
    n = len(modules)
    for i, (key, fn, label) in enumerate(modules):
        if s.get(key, True):
            _set_progress(int(i*100/n), label)
            try:
                results.append(fn())
            except Exception as exc:
                err(f"{label} loi: {exc}")
                log(traceback.format_exc(), "error")
    if s.get("clean_old_downloads"):
        results.append(cleanup_old_downloads(s.get("old_downloads_days", 30)))
    if s.get("optimize_drives"):
        optimize_drives()
    if s.get("optimize_network"):
        optimize_network()
    _set_progress(100, "Xong")
    _end_progress()
    return results

def full_cleaner(s: dict = None) -> list:
    if s is None:
        s = load_settings()
    section("Full Cleaner – Don Dep Toan Dien")
    t0 = time.time()
    free_before = free_space_gb()
    results     = _run_full_clean(s)
    free_after  = free_space_gb()
    duration    = round(time.time() - t0, 1)
    gained      = round(free_after - free_before, 1)
    ok(f"Full Cleaner xong trong {duration}s | Truoc: {free_before}GB | Sau: {free_after}GB | +{gained}GB")
    note(f"Full Cleaner: giai phong ~{gained}GB trong {duration}s")
    # Update last_run
    s["last_run"] = datetime.now().isoformat(timespec="seconds")
    save_settings(s)
    return results

def safe_everyday_profile(s=None):
    if s is None: s = load_settings()
    section("Safe Everyday Profile")
    if s.get("auto_restore_point"): create_restore_point()
    optimize_gaming_registry(); optimize_visuals(); optimize_mouse()
    apply_power_profile("everyday")
    cleanup_temp_files()
    if s.get("optimize_drives"): optimize_drives()
    ok("Hoan tat Safe Everyday profile")

def gaming_plus_profile(s=None):
    if s is None: s = load_settings()
    section("Gaming Plus Profile")
    if s.get("auto_restore_point"): create_restore_point()
    optimize_gaming_registry(); optimize_visuals(); optimize_mouse()
    if IS_WIN10_PLUS and WIN_BUILD >= 19041: enable_hags()
    apply_power_profile("gaming_plus")
    cleanup_temp_files()
    if s.get("optimize_drives"): optimize_drives()
    ok("Hoan tat Gaming Plus profile")
    warn("Restart de HAGS nhan chac hon.")

def competitive_profile(s=None):
    if s is None: s = load_settings()
    section("Competitive Extreme Profile")
    if s.get("auto_restore_point"): create_restore_point()
    optimize_gaming_registry(); optimize_visuals(); optimize_mouse()
    optimize_low_latency_registry()
    if IS_WIN10_PLUS and WIN_BUILD >= 19041: enable_hags()
    apply_power_profile("competitive")
    apply_task_trim(); apply_service_trim(extreme=True)
    optimize_network_registry()
    cleanup_temp_files()
    ok("Hoan tat Competitive Extreme profile")
    warn("WSearch / Telemetry da bi tat. Nen restart.")

def desktop_max_profile(s=None):
    if s is None: s = load_settings()
    section("Desktop Max Extreme Profile")
    if s.get("auto_restore_point"): create_restore_point()
    optimize_gaming_registry(); optimize_mouse(); optimize_low_latency_registry()
    if IS_WIN10_PLUS and WIN_BUILD >= 19041: enable_hags()
    apply_power_profile("desktop_max")
    apply_task_trim(); apply_service_trim(extreme=True)
    optimize_network_registry()
    ok("Hoan tat Desktop Max Extreme profile")
    warn("Desktop Max rat nong & ton dien. Chi dung cho may ban tan nhiet tot.")

def laptop_profile(s=None):
    if s is None: s = load_settings()
    section("Laptop Turbo Profile")
    if s.get("auto_restore_point"): create_restore_point()
    optimize_gaming_registry(); optimize_visuals(); optimize_mouse()
    if IS_WIN10_PLUS and WIN_BUILD >= 19041: enable_hags()
    apply_power_profile("laptop")
    cleanup_temp_files()
    if s.get("optimize_drives"): optimize_drives()
    ok("Hoan tat Laptop Turbo profile")

def auto_tune(s=None):
    if s is None: s = load_settings()
    section("Auto Tune")
    if has_battery():
        info("May co pin → Laptop Turbo")
        laptop_profile(s)
    else:
        info("May ban → Gaming Plus")
        gaming_plus_profile(s)

def restore_all():
    section("Restore All – Phuc Hoi Toan Bo")
    restore_registry_values()
    restore_startup_items()
    restore_task_changes()
    restore_service_changes()
    restore_power_changes()
    ok("Phuc hoi hoan tat. Nen restart may.")

def quick_report() -> dict:
    section("Bao Cao Nhanh")
    si = get_full_sysinfo()
    info(f"OS     : {si['os_caption']} | Build {si['os_build']}")
    info(f"Python : {si['python']}")
    info(f"RAM    : {si['ram_gb']} GB")
    info(f"CPU    : {si['cpu_name']} | {si['cpu_cores']}c/{si['cpu_logical']}t @ {si['cpu_mhz']}MHz")
    for g in si["gpus"]:
        info(f"GPU    : {g['name']} | Driver {g['driver']} | VRAM {g['vram_mb']}MB")
    used_c = round(si["total_c_gb"] - si["free_c_gb"], 1)
    pct    = int(used_c*100/si["total_c_gb"]) if si["total_c_gb"] else 0
    info(f"O C:   : Tong {si['total_c_gb']}GB | Da dung {used_c}GB ({pct}%) | Con {si['free_c_gb']}GB")
    ag, an = get_active_power_scheme()
    info(f"Power  : {an or 'Unknown'} ({ag or '?'})")
    if IS_WIN7:
        warn("Windows 7 het ho tro bao mat tu 01/2020!")
    if IS_WIN10_PLUS and date.today() > WIN10_EOS:
        warn("Windows 10 het ho tro tu 14/10/2025!")
    return si

# =============================================================================
#  SESSION STATS  (v6 – tich luy ket qua trong phien lam viec)
# =============================================================================
class SessionStats:
    """Theo doi tong ket qua don dep trong mot phien."""
    def __init__(self):
        self.reset()

    def reset(self):
        self.freed   = 0
        self.deleted = 0
        self.runs    = 0
        self.started = datetime.now()

    def add(self, result):
        if hasattr(result, "freed"):
            self.freed   += result.freed
            self.deleted += result.deleted
        self.runs += 1

    def summary(self) -> str:
        elapsed = int((datetime.now() - self.started).total_seconds())
        return (f"Phien lam viec: {self.runs} lan chay | "
                f"Tong giai phong: {fmt_bytes(self.freed)} | "
                f"Files xoa: {self.deleted:,} | "
                f"Thoi gian: {elapsed}s")

_session = SessionStats()

# =============================================================================
#  RAM / MEMORY CLEANER  (v6 – EmptyWorkingSet + Standby List)
# =============================================================================
_KERNEL32      = ctypes.windll.kernel32 if platform.system() == "Windows" else None
_PSAPI         = ctypes.windll.psapi    if platform.system() == "Windows" else None
_ADVAPI32      = ctypes.windll.advapi32 if platform.system() == "Windows" else None
SE_DEBUG_NAME  = "SeDebugPrivilege"
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value if platform.system() == "Windows" else -1

def _setup_win32_signatures():
    """
    [PATCHED v9.1 – CRITICAL] Khai bao argtypes/restype cho cac ham Win32.
    Mac dinh ctypes coi restype la C int (32-bit) -> tren Windows 64-bit, cac
    HANDLE/con tro tra ve bi cat ngan/sai dau -> truy cap sai vung nho, crash.
    Goi 1 lan luc khoi dong. An toan khi goi nhieu lan (idempotent).
    """
    if platform.system() != "Windows":
        return
    try:
        import ctypes.wintypes as wt
        k = _KERNEL32
        k.GetCurrentProcess.restype          = wt.HANDLE
        k.OpenProcess.restype                = wt.HANDLE
        k.OpenProcess.argtypes               = [wt.DWORD, wt.BOOL, wt.DWORD]
        k.OpenProcessToken.argtypes          = [wt.HANDLE, wt.DWORD, ctypes.POINTER(wt.HANDLE)]
        k.OpenProcessToken.restype           = wt.BOOL
        k.CloseHandle.argtypes               = [wt.HANDLE]
        k.CloseHandle.restype                = wt.BOOL
        k.CreateToolhelp32Snapshot.restype   = wt.HANDLE
        k.CreateToolhelp32Snapshot.argtypes  = [wt.DWORD, wt.DWORD]
        k.GetFileAttributesW.argtypes        = [wt.LPCWSTR]
        k.GetFileAttributesW.restype         = wt.DWORD
        k.GlobalMemoryStatusEx.restype       = wt.BOOL
        k.GetSystemTimes.restype             = wt.BOOL

        a = _ADVAPI32
        a.LookupPrivilegeValueW.argtypes     = [wt.LPCWSTR, wt.LPCWSTR, ctypes.POINTER(ctypes.c_int64)]
        a.LookupPrivilegeValueW.restype      = wt.BOOL
        a.AdjustTokenPrivileges.argtypes     = [wt.HANDLE, wt.BOOL, ctypes.c_void_p,
                                                wt.DWORD, ctypes.c_void_p, ctypes.c_void_p]
        a.AdjustTokenPrivileges.restype      = wt.BOOL

        p = _PSAPI
        p.EmptyWorkingSet.argtypes           = [wt.HANDLE]
        p.EmptyWorkingSet.restype            = wt.BOOL
    except Exception:
        pass

def _enable_se_debug() -> bool:
    """Mo quyen SeDebugPrivilege de truy cap process cua he thong."""
    try:
        import ctypes.wintypes as wt
        TOKEN_ADJUST_PRIVILEGES = 0x0020
        TOKEN_QUERY             = 0x0008
        SE_PRIVILEGE_ENABLED    = 0x00000002
        h_token = wt.HANDLE()
        _KERNEL32.OpenProcessToken(
            _KERNEL32.GetCurrentProcess(),
            TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY,
            ctypes.byref(h_token)
        )
        luid = ctypes.c_int64(0)
        ctypes.windll.advapi32.LookupPrivilegeValueW(None, SE_DEBUG_NAME, ctypes.byref(luid))

        class LUID_AND_ATTR(ctypes.Structure):
            _fields_ = [("Luid", ctypes.c_int64), ("Attributes", ctypes.c_ulong)]

        class TOKEN_PRIVILEGES(ctypes.Structure):
            _fields_ = [("PrivilegeCount", ctypes.c_ulong),
                        ("Privileges",     LUID_AND_ATTR * 1)]

        tp = TOKEN_PRIVILEGES()
        tp.PrivilegeCount         = 1
        tp.Privileges[0].Luid     = luid.value
        tp.Privileges[0].Attributes = SE_PRIVILEGE_ENABLED
        ctypes.windll.advapi32.AdjustTokenPrivileges(
            h_token, False, ctypes.byref(tp), 0, None, None
        )
        _KERNEL32.CloseHandle(h_token)
        return True
    except Exception:
        return False

def get_ram_usage() -> dict:
    """
    Tra ve dict voi total/used/free tinh bang GB.
    [PATCHED] Dung ctypes GlobalMemoryStatusEx (khong sinh tien trinh con)
    thay vi wmic (khong chay tren Win11 moi).
    """
    try:
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength",                ctypes.c_ulong),
                ("dwMemoryLoad",            ctypes.c_ulong),
                ("ullTotalPhys",            ctypes.c_ulonglong),
                ("ullAvailPhys",            ctypes.c_ulonglong),
                ("ullTotalPageFile",        ctypes.c_ulonglong),
                ("ullAvailPageFile",        ctypes.c_ulonglong),
                ("ullTotalVirtual",         ctypes.c_ulonglong),
                ("ullAvailVirtual",         ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]
        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            raise OSError("GlobalMemoryStatusEx that bai")
        total_gb = round(stat.ullTotalPhys  / (1024 ** 3), 2)
        free_gb  = round(stat.ullAvailPhys  / (1024 ** 3), 2)
        used_gb  = round(total_gb - free_gb, 2)
        pct      = int(stat.dwMemoryLoad)  # gia tri chinh xac tu OS
        return {"total": total_gb, "used": used_gb, "free": free_gb, "pct": pct}
    except Exception:
        pass
    # Fallback PowerShell neu ctypes khong kha dung
    try:
        ok_, out, _ = ps(
            "Get-CimInstance Win32_OperatingSystem | "
            "Select-Object TotalVisibleMemorySize,FreePhysicalMemory | ConvertTo-Json -Compress",
            timeout=10
        )
        if ok_ and out:
            d = json.loads(out)
            total_kb = int(d.get("TotalVisibleMemorySize") or 0)
            free_kb  = int(d.get("FreePhysicalMemory")     or 0)
            total_gb = round(total_kb / (1024 ** 2), 2)
            free_gb  = round(free_kb  / (1024 ** 2), 2)
            used_gb  = round(total_gb - free_gb, 2)
            pct      = int(used_gb * 100 / total_gb) if total_gb else 0
            return {"total": total_gb, "used": used_gb, "free": free_gb, "pct": pct}
    except Exception:
        pass
    return {"total": 0, "used": 0, "free": 0, "pct": 0}

def cleanup_ram() -> dict:
    """
    Giai phong Standby Memory bang cach goi EmptyWorkingSet tren moi process
    va dung PowerShell Empty-Standby-List.
    Tra ve {"before": GB, "after": GB, "freed": GB}.
    """
    section("RAM / Memory Cleanup")
    before = get_ram_usage()
    info(f"Truoc: RAM su dung {before['used']}GB / {before['total']}GB ({before['pct']}%)")

    freed_procs = 0
    if _KERNEL32 and _PSAPI:
        _enable_se_debug()
        PROCESS_ALL_ACCESS   = 0x1F0FFF
        TH32CS_SNAPPROCESS   = 0x00000002

        class PROCESSENTRY32(ctypes.Structure):
            _fields_ = [
                ("dwSize",              ctypes.c_ulong),
                ("cntUsage",            ctypes.c_ulong),
                ("th32ProcessID",       ctypes.c_ulong),
                ("th32DefaultHeapID",   ctypes.c_size_t),
                ("th32ModuleID",        ctypes.c_ulong),
                ("cntThreads",          ctypes.c_ulong),
                ("th32ParentProcessID", ctypes.c_ulong),
                ("pcPriClassBase",      ctypes.c_long),
                ("dwFlags",             ctypes.c_ulong),
                ("szExeFile",           ctypes.c_char * 260),
            ]

        snap = _KERNEL32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snap and snap != _INVALID_HANDLE_VALUE:
            entry = PROCESSENTRY32()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
            ok_proc = _KERNEL32.Process32First(snap, ctypes.byref(entry))
            while ok_proc:
                pid  = entry.th32ProcessID
                h    = _KERNEL32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
                if h:
                    try:
                        # EmptyWorkingSet la ham C tra ve BOOL, KHONG raise exception.
                        # Phai kiem tra gia tri tra ve de dem chinh xac.
                        if _PSAPI.EmptyWorkingSet(h):
                            freed_procs += 1
                    except Exception:
                        pass
                    _KERNEL32.CloseHandle(h)
                ok_proc = _KERNEL32.Process32Next(snap, ctypes.byref(entry))
            _KERNEL32.CloseHandle(snap)
        ok(f"EmptyWorkingSet tren {freed_procs} process")

    # Standby list via PowerShell (chi Win8+).
    # [PATCHED v9.1] Phai truyen lenh MemoryPurgeStandbyList (=4) vao buffer,
    # khong phai IntPtr.Zero. SystemMemoryListInformation = 80.
    if IS_WIN8_PLUS:
        sok, _o, _e = ps(
            "$code = @\"\n[DllImport(\"ntdll.dll\")]\n"
            "public static extern uint NtSetSystemInformation(int InfoClass, IntPtr Info, int Length);\n\"@\n"
            "$api = Add-Type -MemberDefinition $code -Name 'NtMemory' -Namespace Win32 -PassThru;\n"
            "$cmd = 4;\n"  # MemoryPurgeStandbyList
            "$buf = [System.Runtime.InteropServices.Marshal]::AllocHGlobal(4);\n"
            "[System.Runtime.InteropServices.Marshal]::WriteInt32($buf, $cmd);\n"
            "$rc = $api::NtSetSystemInformation(80, $buf, 4);\n"
            "[System.Runtime.InteropServices.Marshal]::FreeHGlobal($buf);\n"
            "if ($rc -ne 0) { Write-Error \"NtSetSystemInformation rc=$rc\" }",
            timeout=30
        )
        if sok:
            ok("Standby List cleared (NtSetSystemInformation)")
        else:
            warn("Khong the xoa Standby List (can quyen Admin / phien ban Windows)")

    # Chay qua rundll32 xu ly idle tasks
    run_cmd(["rundll32.exe","advapi32.dll,ProcessIdleTasks"], shell=False, timeout=30)

    time.sleep(1)
    after = get_ram_usage()
    gained = round(after["free"] - before["free"], 2)
    info(f"Sau : RAM su dung {after['used']}GB / {after['total']}GB ({after['pct']}%)")
    ok(f"RAM Cleanup xong – giai phong ~{gained}GB")
    return {"before": before["free"], "after": after["free"], "freed": gained}

# =============================================================================
#  DISK ANALYZER  (v6 – top N thu muc chiem nhieu dung luong nhat)
# =============================================================================
def analyze_disk_space(root: str = None, top_n: int = 15, max_depth: int = 4) -> list:
    """
    Quet root (mac dinh SYSDRIVE), tra ve list [(path, size_bytes)] sorted desc.
    max_depth gioi han do sau de tranh qua cham.
    """
    if root is None:
        root = SYSDRIVE + "\\"
    section(f"Disk Analyzer – Top {top_n} thu muc ({root})")
    info("Dang quet... (co the mat vai giay)")

    results = []
    root = os.path.abspath(root)

    def _get_size(path: str, depth: int) -> int:
        total = 0
        if depth > max_depth:
            return total
        try:
            with os.scandir(path) as it:
                for entry in it:
                    try:
                        if entry.is_file(follow_symlinks=False):
                            total += entry.stat().st_size
                        elif entry.is_dir(follow_symlinks=False):
                            sub = _get_size(entry.path, depth + 1)
                            total += sub
                            if depth <= 1:
                                results.append((entry.path, sub))
                    except (PermissionError, OSError):
                        pass
        except (PermissionError, OSError):
            pass
        return total

    _get_size(root, 0)
    results.sort(key=lambda x: x[1], reverse=True)
    top = results[:top_n]

    total_used = sum(x[1] for x in results)
    print()
    for i, (path, sz) in enumerate(top, 1):
        pct = int(sz * 100 / total_used) if total_used else 0
        bar = "█" * min(pct, 40)
        print(f"  {i:2d}. {fmt_bytes(sz):>10}  {bar:<40}  {os.path.basename(path) or path}")
    print()
    ok(f"Quet xong. Tong {len(results)} thu muc, lon nhat: {fmt_bytes(top[0][1]) if top else '0'}")
    return top

# =============================================================================
#  SSD DETECTION & TRIM  (v6)
# =============================================================================
def detect_ssd_drives() -> list:
    """Tra ve list chu cai o dia SSD (tren Win8+ dung Get-PhysicalDisk)."""
    ssds = []
    if not IS_WIN8_PLUS:
        return ssds
    ok_, out, _ = ps(
        "Get-PhysicalDisk -ErrorAction SilentlyContinue | "
        "Where-Object {$_.MediaType -eq 'SSD'} | "
        "Select-Object -ExpandProperty DeviceId",
        timeout=30
    )
    if not ok_:
        return ssds
    # Map DeviceId -> drive letters qua Get-Partition
    ssd_ids = [l.strip() for l in out.splitlines() if l.strip().isdigit()]
    for disk_id in ssd_ids:
        ok2, out2, _ = ps(
            f"Get-Partition -DiskNumber {disk_id} -ErrorAction SilentlyContinue | "
            "Where-Object {$_.DriveLetter} | "
            "Select-Object -ExpandProperty DriveLetter",
            timeout=30
        )
        if ok2:
            for line in out2.splitlines():
                letter = line.strip().strip(":").upper()
                if re.fullmatch(r"[A-Z]", letter) and letter not in ssds:
                    ssds.append(letter)
    return ssds

def run_ssd_trim(drives: list = None):
    """Chay Optimize-Volume (TRIM) cho cac o SSD."""
    section("SSD TRIM")
    if not IS_WIN8_PLUS:
        warn("TRIM chi ho tro tren Win8+. Bo qua.")
        return
    ssds = drives or detect_ssd_drives()
    if not ssds:
        info("Khong phat hien SSD nao (hoac khong phan biet duoc). Thu TRIM toan bo o dia...")
        ssds = detect_fixed_drives()
    for drive in ssds:
        ok_, out, err_ = ps(
            f"Optimize-Volume -DriveLetter {drive} -ReTrim -Verbose -ErrorAction SilentlyContinue",
            timeout=300
        )
        if ok_:
            ok(f"SSD TRIM hoan thanh: {drive}:")
        else:
            # Fallback: defrag /L (TRIM command on Win8+)
            ok2, _, _ = run_cmd(["defrag", f"{drive}:", "/L"], shell=False, timeout=180)
            if ok2:
                ok(f"TRIM (defrag /L): {drive}:")
            else:
                warn(f"TRIM that bai cho {drive}: {err_ or ''}")

# =============================================================================
#  PAGEFILE OPTIMIZER  (v6)
# =============================================================================
def optimize_pagefile(mode: str = "auto"):
    """
    Toi uu pagefile.sys theo che do:
      auto    – de Windows tu quan ly (khong khuyen dung cho may it RAM)
      smart   – dat Initial=RAM*1.5, Max=RAM*3 (chat luong on dinh)
      gaming  – dat Initial=RAM, Max=RAM*2 (giam I/O page)
      disable – tat pagefile (CHI cho may 16GB+ RAM, rui ro cao)
    """
    section(f"Pagefile Optimizer (mode={mode})")
    ram_gb = get_memory_gb() or 8
    c_drive = SYSDRIVE.rstrip("\\")

    if mode == "auto":
        ps(
            '$cs = Get-WmiObject Win32_ComputerSystem -ErrorAction SilentlyContinue; '
            '$cs.AutomaticManagedPagefile = $True; '
            '$cs.Put() | Out-Null',
            timeout=30
        )
        ok("Pagefile = Windows tu quan ly (Automatic)")
        return

    # Tat auto truoc
    ps(
        '$cs = Get-WmiObject Win32_ComputerSystem -ErrorAction SilentlyContinue; '
        '$cs.AutomaticManagedPagefile = $False; '
        '$cs.Put() | Out-Null',
        timeout=30
    )

    if mode == "disable":
        if ram_gb < 16:
            warn(f"RAM chi co {ram_gb}GB. Tat pagefile co the gay crash! Can it nhat 16GB. Bo qua.")
            return
        ok_, _, _ = ps(
            f'$pf = Get-WmiObject -Query "SELECT * FROM Win32_PageFileSetting WHERE Name LIKE \'{c_drive}%\'" '
            '-ErrorAction SilentlyContinue; if ($pf) {{ $pf.Delete() }}',
            timeout=30
        )
        if ok_:
            ok("Da xoa pagefile (tat hoan toan). Can restart.")
        warn("Tat pagefile: chi nen dung khi RAM >= 16GB va khong co chuong trinh nang.")
        return

    if mode == "smart":
        init_mb = int(ram_gb * 1024 * 1.5)
        max_mb  = int(ram_gb * 1024 * 3)
    else:  # gaming
        init_mb = int(ram_gb * 1024)
        max_mb  = int(ram_gb * 1024 * 2)

    # [PATCHED v2] Hard cap de bao ve o SSD dung luong thap:
    # Tren may 64GB RAM: smart tinh max = 192GB → cap lai o 16GB
    # Tren may 128GB RAM: smart tinh max = 384GB → cap lai o 16GB
    # Nguong phai: 2GB init min, 4GB max min; 8GB init max, 16GB max max
    # Kiem tra them: neu free disk < max_mb * 1.5 → tu dong giam xuong
    init_mb = min(8192,  max(2048, init_mb))
    max_mb  = min(16384, max(4096, max_mb))
    # Kiem tra dung luong o C con lai de tranh lam day partition
    try:
        _, _, free_c = shutil.disk_usage(SYSDRIVE + "\\")
        free_c_mb = free_c // (1 << 20)
        # Giu it nhat 20GB trong sau khi dat pagefile
        safe_max = max(4096, free_c_mb - 20480)
        if max_mb > safe_max:
            warn(f"O C chi con {free_c_mb // 1024}GB: tu dong giam pagefile max tu {max_mb}MB xuong {safe_max}MB")
            max_mb  = safe_max
            init_mb = min(init_mb, max_mb // 2)
    except Exception:
        pass

    ok_, _, err_ = ps(
        f'$pf = Get-WmiObject -Query "SELECT * FROM Win32_PageFileSetting WHERE Name LIKE \'{c_drive}%\'" '
        '-ErrorAction SilentlyContinue; '
        f'if ($pf) {{ $pf.InitialSize = {init_mb}; $pf.MaximumSize = {max_mb}; $pf.Put() | Out-Null }} '
        f'else {{ Set-WMIInstance -Class Win32_PageFileSetting '
        f'-Arguments @{{Name="{c_drive}\\pagefile.sys"; InitialSize={init_mb}; MaximumSize={max_mb}}} | Out-Null }}',
        timeout=30
    )
    if ok_:
        ok(f"Pagefile: Initial={init_mb}MB, Max={max_mb}MB (RAM={ram_gb}GB, mode={mode}). Can restart.")
    else:
        warn(f"Khong doi duoc pagefile: {err_}")

# =============================================================================
#  HIBERNATION MANAGER  (v6)
# =============================================================================
def get_hibernation_state() -> bool:
    """Tra ve True neu Hibernate dang bat."""
    ok_, out, _ = run_cmd(["powercfg","/a"], shell=False, timeout=30)
    if ok_:
        for line in out.lower().splitlines():
            if "hibernate" in line and "not available" not in line and "disabled" not in line:
                return True
    return False

def get_hiberfil_size_gb() -> float:
    hf = os.path.join(SYSDRIVE + "\\", "hiberfil.sys")
    try:
        return round(os.path.getsize(hf) / (1 << 30), 2)
    except Exception:
        return 0.0

def toggle_hibernation(enable: bool):
    """Bat hoac tat Hibernate."""
    section("Hibernation Manager")
    hf_size = get_hiberfil_size_gb()
    if enable:
        ok_, _, _ = run_cmd(["powercfg","/hibernate","on"], shell=False)
        if ok_: ok("Hibernate = ON")
        else:   warn("Khong bat duoc Hibernate")
    else:
        info(f"Dang tat Hibernate – se giai phong ~{hf_size}GB (hiberfil.sys)...")
        ok_, _, _ = run_cmd(["powercfg","/hibernate","off"], shell=False)
        if ok_:
            ok(f"Hibernate = OFF | Giai phong ~{hf_size}GB")
            note(f"Hibernate disabled, freed ~{hf_size}GB")
        else:
            warn("Khong tat duoc Hibernate")

# =============================================================================
#  EVENT LOG CLEANER  (v6)
# =============================================================================
def cleanup_event_logs(older_than_days: int = 30) -> CleanResult:
    """Xoa Windows Event Log cu qua {older_than_days} ngay."""
    section(f"Event Log Cleanup (log cu > {older_than_days} ngay)")
    r = CleanResult("EventLog")

    # .evtx files trong winevt/Logs
    evtx_dir = os.path.join(WINDIR, r"System32\winevt\Logs")
    f, d = _del_files_recursive(evtx_dir, patterns=["*.evtx_bak","*.evtx.old"], older_than_days=0)
    r.add("Event Log backups", f, d)

    # Xoa noi dung log qua wevtutil (chi backup, khong xoa file chinh)
    if IS_WIN8_PLUS:
        ok_, out, _ = ps(
            "Get-WinEvent -ListLog * -ErrorAction SilentlyContinue | "
            "Where-Object {$_.RecordCount -gt 0} | "
            "Select-Object -ExpandProperty LogName",
            timeout=30
        )
        logs_cleared = 0
        if ok_:
            for log_name in out.splitlines():
                log_name = log_name.strip()
                if not log_name:
                    continue
                ok2, _, _ = run_cmd(
                    ["wevtutil", "cl", log_name], shell=False, timeout=15
                )
                if ok2:
                    logs_cleared += 1
            ok(f"Da xoa noi dung {logs_cleared} event logs")
    else:
        # Win7: dung wevtutil truc tiep
        common_logs = [
            "Application", "System", "Security",
            "Setup", "Microsoft-Windows-TaskScheduler/Operational"
        ]
        for log_name in common_logs:
            run_cmd(["wevtutil", "cl", log_name], shell=False, timeout=15)
        ok("Da xoa 5 event log chinh (Win7 mode)")

    ok(r.summary())
    return r

# =============================================================================
#  FONT CACHE REBUILD  (v6)
# =============================================================================
def rebuild_font_cache():
    """
    Xoa Font Cache de Windows rebuild. Sua loi font hien thi sai/lo.
    Can restart sau khi chay.
    """
    section("Font Cache Rebuild")
    # Dung sc de stop font cache service
    fc_service = "FontCache" if IS_WIN8_PLUS else "FontCache3.0.0.0"
    sc_stop(fc_service)

    cache_paths = []
    if LOCALAPPDATA:
        cache_paths += [
            os.path.join(LOCALAPPDATA, r"Microsoft\Windows\Fonts"),
        ]
    # Win7/8/10 font cache files
    cache_paths += [
        os.path.join(WINDIR, r"ServiceProfiles\LocalService\AppData\Local\FontCache"),
        os.path.join(WINDIR, r"ServiceProfiles\LocalService\AppData\Local\Microsoft\Windows\Fonts"),
    ]

    freed = count = 0
    for p in cache_paths:
        f, d = _del_dir_contents(p)
        freed += f
        count += d

    # Xoa font cache dat files
    fc_dat = os.path.join(WINDIR, r"System32\FNTCACHE.DAT")
    if os.path.exists(fc_dat):
        try:
            freed += os.path.getsize(fc_dat)
            os.remove(fc_dat)
            count += 1
            ok(f"Xoa FNTCACHE.DAT: {fc_dat}")
        except Exception as exc:
            warn(f"Khong xoa duoc FNTCACHE.DAT: {exc}")

    sc_start(fc_service)
    ok(f"Font Cache Rebuild: {fmt_bytes(freed)}, {count} files. Restart de hoan tat.")

# =============================================================================
#  ADDITIONAL REGISTRY TWEAKS  (v6 – 20+ tweak moi)
# =============================================================================
def optimize_extra_tweaks():
    """
    Tap hop >20 registry tweak nang cao, tuong thich Win7+.
    Tap trung vao: startup speed, explorer, network stack, input lag.
    """
    section("Extra Performance Tweaks (v6)")
    backup_registry_values()

    items = []

    # ── Explorer / Shell tweaks ──────────────────────────────────────────────
    items += [
        ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced",
         "LaunchTo",             1, REG_DWORD, "Explorer: mo 'This PC' thay vi Quick Access"),
        ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced",
         "SeparateProcess",      1, REG_DWORD, "Explorer: moi cua so la process rieng (on dinh hon)"),
        ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced",
         "ShowSuperHidden",      0, REG_DWORD, "Explorer: an file he thong sieu an"),
        ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Explorer",
         "EnableAutoTray",       1, REG_DWORD, "Taskbar: an icon tray khong dung"),
        ("HKCU", r"Control Panel\Desktop",
         "JPEGImportQuality",    100, REG_DWORD, "JPEG thumbnail quality = max"),
        ("HKCU", r"Control Panel\Desktop",
         "LowLevelHooksTimeout", "1000", REG_SZ, "LowLevelHooks timeout = 1s"),
        ("HKCU", r"Control Panel\Desktop",
         "ForegroundFlashCount", "0", REG_SZ,  "Tat taskbar button flash khi app boc len"),
        ("HKCU", r"Control Panel\Desktop",
         "DragFullWindows",      "0", REG_SZ,  "Keo cua so: chi hien khung, khong render noi dung"),
    ]

    # ── Network stack tweaks ─────────────────────────────────────────────────
    items += [
        ("HKLM", r"SYSTEM\CurrentControlSet\Services\LanmanServer\Parameters",
         "IRPStackSize",         20,  REG_DWORD, "SMB IRP Stack Size = 20 (mang on dinh hon)"),
        ("HKLM", r"SYSTEM\CurrentControlSet\Services\LanmanServer\Parameters",
         "Size",                 3,   REG_DWORD, "SMB Server Size = 3 (large)"),
        ("HKLM", r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters",
         "TcpTimedWaitDelay",    30,  REG_DWORD, "TCP TimeWait = 30s (mac dinh 240s)"),
        ("HKLM", r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters",
         "EnablePMTUDiscovery",  1,   REG_DWORD, "TCP PMTU Discovery = ON"),
        ("HKLM", r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters",
         "Tcp1323Opts",          1,   REG_DWORD, "TCP 1323 Options (timestamps + window scaling)"),
        ("HKLM", r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters",
         "DefaultTTL",           64,  REG_DWORD, "Default TTL = 64 (tieu chuan Linux/Mac)"),
        ("HKLM", r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters",
         "MaxUserPort",          65534, REG_DWORD, "Max UDP/TCP user port = 65534"),
        ("HKLM", r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters",
         "TcpMaxDataRetransmissions", 3, REG_DWORD, "TCP Max Retransmissions = 3 (giam timeout)"),
    ]

    # ── NTFS / Disk ──────────────────────────────────────────────────────────
    items += [
        ("HKLM", r"SYSTEM\CurrentControlSet\Control\FileSystem",
         "ContigFileAllocSize",  512, REG_DWORD, "NTFS Contig alloc = 512 (giam phan manh)"),
    ]

    # ── Input / Keyboard ─────────────────────────────────────────────────────
    items += [
        ("HKCU", r"Control Panel\Keyboard",
         "InitialKeyboardIndicators", "0", REG_SZ,  "Tat Num Lock khi boot (tuy chon)"),
        ("HKCU", r"Control Panel\Keyboard",
         "KeyboardDelay",             "0", REG_SZ,  "Keyboard delay = 0 (nhanh nhat)"),
        ("HKCU", r"Control Panel\Keyboard",
         "KeyboardSpeed",             "31", REG_SZ, "Keyboard repeat speed = 31 (nhanh nhat)"),
    ]

    # ── Win10+ only ──────────────────────────────────────────────────────────
    if IS_WIN10_PLUS:
        items += [
            # Tat Cortana / Search indexing cloud
            ("HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Search",
             "BingSearchEnabled",   0, REG_DWORD, "Cortana Bing Search = OFF"),
            ("HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Search",
             "CortanaConsent",      0, REG_DWORD, "Cortana Consent = OFF"),
            ("HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Search",
             "AllowSearchToUseLocation", 0, REG_DWORD, "Search location = OFF"),
            # Tat Windows Tips / Suggestions
            ("HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\ContentDeliveryManager",
             "SubscribedContent-338388Enabled", 0, REG_DWORD, "Spotlight suggestions = OFF"),
            ("HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\ContentDeliveryManager",
             "SubscribedContent-310093Enabled", 0, REG_DWORD, "Tips & tricks = OFF"),
            ("HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\ContentDeliveryManager",
             "SoftLandingEnabled",  0, REG_DWORD, "Soft landing suggestions = OFF"),
            # Tat "Get even more out of Windows" notification
            ("HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\UserProfileEngagement",
             "ScoobeSystemSettingEnabled", 0, REG_DWORD, "OOBE suggestions = OFF"),
        ]

    done = total = 0
    for hive, path, name, value, regtype, label in items:
        total += 1
        ok_, _, _ = reg_add(hive, path, name, value, regtype)
        if ok_:
            ok(label)
            done += 1
        else:
            warn(f"Bo qua: {label}")
    info(f"Extra tweaks: {done}/{total} thanh cong")

# =============================================================================
#  ADDITIONAL SERVICES TO DISABLE  (v6)
# =============================================================================
_EXTRA_V6_SERVICES = [
    "PcaSvc",      # Program Compatibility Assistant
    "SensrSvc",    # Sensors Monitoring Service (laptop cam bien)
    "WbioSrvc",    # Windows Biometric (van tay – neu khong dung)
    "icssvc",      # Windows Mobile Hotspot
    "SharedAccess", # Internet Connection Sharing
    "XblAuthManager",    # Xbox Live Auth (Win10)
    "XblGameSave",       # Xbox Live Game Save (Win10)
]

def get_extra_v6_services():
    services = list(_EXTRA_V6_SERVICES)
    if not IS_WIN10_PLUS:
        services = [s for s in services if "xbox" not in s.lower() and "Xbl" not in s]
    return services

# =============================================================================
#  WINDOWS NOTIFICATIONS  (v6 – balloon tip sau khi hoan thanh)
# =============================================================================
def _show_balloon(title: str, msg: str, duration: int = 5):
    """Hien thi Windows notification/balloon tip."""
    try:
        if IS_WIN10_PLUS:
            # PowerShell Toast Notification
            ps_cmd = (
                '[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, '
                'ContentType = WindowsRuntime] | Out-Null; '
                '[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, '
                'ContentType = WindowsRuntime] | Out-Null; '
                f'$xml = [Windows.UI.Notifications.ToastNotificationManager]'
                f'::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02); '
                f'$xml.GetElementsByTagName("text")[0].AppendChild($xml.CreateTextNode("{title}")) | Out-Null; '
                f'$xml.GetElementsByTagName("text")[1].AppendChild($xml.CreateTextNode("{msg}")) | Out-Null; '
                f'$toast = [Windows.UI.Notifications.ToastNotification]::new($xml); '
                f'[Windows.UI.Notifications.ToastNotificationManager]'
                f'::CreateToastNotifier("WinOptimizer").Show($toast)'
            )
            ps(ps_cmd, timeout=10)
        else:
            # Win7: dung PowerShell MsgBox thay vi mshta javascript (tranh injection qua msg/title)
            # Escape single quote trong msg/title truoc khi truyen vao PS string
            safe_title = str(title).replace("'", "''")
            safe_msg   = str(msg).replace("'", "''")
            run_cmd(
                ["powershell", "-NoProfile", "-Command",
                 f"(New-Object -ComObject WScript.Shell).Popup('{safe_msg}',{int(duration)},'{safe_title}',64)"],
                shell=False, timeout=duration + 3
            )
    except Exception:
        pass  # Notification la phu, khong quan trong neu that bai

# =============================================================================
#  EXPORT / IMPORT SETTINGS  (v6)
# =============================================================================
def export_settings(path: str) -> bool:
    s = load_settings()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False, indent=2)
        ok(f"Da xuat settings ra: {path}")
        return True
    except Exception as exc:
        err(f"Xuat settings that bai: {exc}")
        return False

def import_settings(path: str) -> bool:
    try:
        with open(path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        merged = dict(_DEFAULT_SETTINGS)
        merged.update(loaded)
        save_settings(merged)
        ok(f"Da nhap settings tu: {path}")
        return True
    except Exception as exc:
        err(f"Nhap settings that bai: {exc}")
        return False

# =============================================================================
#  WINDOWS 11 DETECTION  (v7)
# =============================================================================
IS_WIN11 = IS_WIN10_PLUS and WIN_BUILD >= 22000

def get_os_friendly_name() -> str:
    if IS_WIN11:                    return "Windows 11"
    if IS_WIN10_PLUS:               return "Windows 10"
    if IS_WIN7:                     return "Windows 7"
    if IS_WIN8_PLUS:                return "Windows 8/8.1"
    return f"Windows (build {WIN_BUILD})"

# Win11-specific tweaks (bat/tat Start menu suggestions, widgets, etc.)
def optimize_win11_tweaks():
    if not IS_WIN11:
        info("Win11 tweaks chi ap dung cho Windows 11. Bo qua.")
        return
    section("Windows 11 Specific Tweaks")
    backup_registry_values()
    items = [
        ("HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Advanced",
         "ShowTaskViewButton",             0, REG_DWORD, "Task View button = OFF"),
        ("HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Advanced",
         "TaskbarDa",                      0, REG_DWORD, "Widgets button = OFF"),
        ("HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Advanced",
         "TaskbarMn",                      0, REG_DWORD, "Chat (Teams) button = OFF"),
        ("HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Search",
         "SearchboxTaskbarMode",           0, REG_DWORD, "Taskbar search = OFF"),
        ("HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Advanced",
         "Start_IrisRecommendations",      0, REG_DWORD, "Start Menu recommendations = OFF"),
        ("HKLM", r"SOFTWARE\Policies\Microsoft\Dsh",
         "AllowNewsAndInterests",          0, REG_DWORD, "News & Interests widget = OFF"),
        ("HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Advanced",
         "UseCompactMode",                 1, REG_DWORD, "File Explorer: compact view = ON"),
        ("HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Themes\Personalize",
         "AppsUseLightTheme",              0, REG_DWORD, "Apps theme = Dark"),
        ("HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Themes\Personalize",
         "SystemUsesLightTheme",           0, REG_DWORD, "System theme = Dark"),
    ]
    done = total = 0
    for hive, path, name, value, regtype, label in items:
        total += 1
        ok_, _, _ = reg_add(hive, path, name, value, regtype)
        if ok_: ok(label); done += 1
        else:   warn(f"Bo qua: {label}")
    info(f"Win11 tweaks: {done}/{total} thanh cong")

# =============================================================================
#  TEMPERATURE MONITOR  (v7)
# =============================================================================
def get_temperatures() -> dict:
    """
    Doc nhiet do CPU/GPU qua WMI MSAcpi_ThermalZoneTemperature.
    Tra ve {"cpu": [list_celsius], "gpu": [list_celsius]}.
    Chi hoat dong tren may ho tro WMI thermal.
    """
    result = {"cpu": [], "gpu": [], "zones": []}
    try:
        raw = wmic(
            r"path MSAcpi_ThermalZoneTemperature get CurrentTemperature /value",
            timeout=10
        )
        for line in raw.splitlines():
            if "CurrentTemperature=" in line:
                raw_k = int(line.split("=", 1)[-1].strip() or "0")
                if raw_k > 0:
                    celsius = round((raw_k - 2732) / 10.0, 1)
                    result["zones"].append(celsius)
        if result["zones"]:
            result["cpu"] = result["zones"][:2]
    except Exception:
        pass

    # GPU via OpenHardwareMonitor / HWiNFO WMI (neu co cai dat)
    try:
        ok_, out, _ = ps(
            'Get-WmiObject -Namespace root/OpenHardwareMonitor '
            '-Class Sensor -ErrorAction SilentlyContinue | '
            'Where-Object {$_.SensorType -eq "Temperature" -and $_.Name -like "*GPU*"} | '
            'Select-Object -ExpandProperty Value',
            timeout=8
        )
        if ok_:
            for line in out.splitlines():
                try:
                    celsius = float(line.strip())
                    result["gpu"].append(celsius)
                except Exception:
                    pass
    except Exception:
        pass

    return result

# =============================================================================
#  PROCESS MANAGER  (v7)
# =============================================================================
def get_top_processes(top_n: int = 20) -> list:
    """
    Tra ve list dict process: name, pid, mem_mb, status.
    [PATCHED] Dung PowerShell Get-Process + ConvertTo-Json thay vi
    ket hop wmic+tasklist cu (O(N^2), cham, khong chay tren Win11 moi).
    Chi mot lenh goi duy nhat, tra ve du lieu co cau truc JSON.
    """
    procs = []
    ps_cmd = (
        f"Get-Process | Where-Object {{$_.WorkingSet64 -gt 0}} | "
        f"Sort-Object -Property WorkingSet64 -Descending | "
        f"Select-Object -First {int(top_n)} -Property "
        f"Name, Id, WorkingSet64, @{{Name='Status';Expression={{$_.Responding}}}} | "
        f"ConvertTo-Json -Compress"
    )
    ok_, out, _ = ps(ps_cmd, timeout=30)
    if not ok_ or not out:
        # Fallback ve tasklist neu PowerShell that bai
        ok2, out2, _ = run_cmd(["tasklist", "/FO", "CSV", "/NH"], shell=False, timeout=20)
        if ok2:
            for row in csv.reader(io.StringIO(out2)):
                if len(row) < 5:
                    continue
                try:
                    name   = row[0].strip('"')
                    pid    = int(row[1].strip('"') or "0")
                    mem_kb = int(row[4].strip('"').replace(",", "").replace(" K", "") or "0")
                    procs.append({"name": name, "pid": pid,
                                  "mem_mb": mem_kb // 1024, "status": "Running"})
                except Exception:
                    pass
            procs.sort(key=lambda x: x["mem_mb"], reverse=True)
            return procs[:top_n]
        return procs

    try:
        data = json.loads(out)
        # ConvertTo-Json tra ve dict neu chi co 1 phan tu
        if isinstance(data, dict):
            data = [data]
        for item in data:
            procs.append({
                "name":   item.get("Name", "Unknown"),
                "pid":    item.get("Id", 0),
                "mem_mb": int(item.get("WorkingSet64", 0)) // (1 << 20),
                "status": "Running" if item.get("Status") else "Not Responding",
            })
    except Exception as e:
        log(f"Loi phan tich JSON du lieu tien trinh: {e}", "error")
    return procs

def kill_process(pid: int) -> bool:
    ok_, _, _ = run_cmd(["taskkill", "/PID", str(pid), "/F"], shell=False, timeout=15)
    return ok_

# =============================================================================
#  NETWORK DIAGNOSTICS  (v7)
# =============================================================================
def get_network_adapters() -> list:
    """
    Tra ve list adapter dang hoat dong voi IP/MAC.
    [PATCHED] PowerShell Get-NetAdapter thay wmic, tuong thich Win11.
    """
    adapters = []
    if IS_WIN8_PLUS:
        ok_, out, _ = ps(
            "Get-NetAdapter | Where-Object {$_.Status -eq 'Up'} | "
            "Select-Object Name,MacAddress,LinkSpeed | ConvertTo-Json -Compress",
            timeout=15
        )
        if ok_ and out:
            try:
                data = json.loads(out)
                if isinstance(data, dict):
                    data = [data]
                for item in data:
                    adapters.append({
                        "Name":       item.get("Name", "?"),
                        "MACAddress": item.get("MacAddress", "?"),
                        "Speed":      str(item.get("LinkSpeed", "?")),
                    })
            except Exception:
                pass
    if not adapters:
        # Fallback wmic (Win7)
        raw = wmic(
            "nic where NetEnabled=true get Name,MACAddress,Speed /value",
            timeout=15
        )
        cur = {}
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                if cur.get("Name"):
                    adapters.append(dict(cur))
                cur = {}
            elif "=" in line:
                k, _, v = line.partition("=")
                cur[k.strip()] = v.strip()

    # Lay IP bang ipconfig /all (khong qua shell, goi truc tiep)
    ok_, out, _ = run_cmd(["ipconfig", "/all"], shell=False, timeout=20)
    ips = []
    for line in (out or "").splitlines():
        m = re.search(r"IPv4 Address.*?:\s*([\d.]+)", line)
        if m:
            ips.append(m.group(1))
    for i, a in enumerate(adapters):
        a["ip"] = ips[i] if i < len(ips) else "N/A"
    return adapters

def ping_test(hosts: list = None, count: int = 4) -> list:
    """
    Ping mot danh sach host, tra ve list dict {host, avg_ms, loss_pct, ok}.
    """
    if hosts is None:
        hosts = ["8.8.8.8", "1.1.1.1", "google.com", "cloudflare.com"]
    results = []
    for host in hosts:
        ok_, out, _ = run_cmd(["ping", "-n", str(count), str(host)], shell=False, timeout=30)
        avg_ms   = None
        loss_pct = 100
        if ok_ or out:
            # Average time
            m = re.search(r"Average\s*=\s*(\d+)ms", out, re.IGNORECASE)
            if m:
                avg_ms = int(m.group(1))
            # Loss
            m2 = re.search(r"\((\d+)%\s*loss\)", out, re.IGNORECASE)
            if m2:
                loss_pct = int(m2.group(1))
        results.append({
            "host":     host,
            "avg_ms":   avg_ms,
            "loss_pct": loss_pct,
            "ok":       avg_ms is not None and loss_pct < 50,
        })
    return results

def dns_benchmark(servers: list = None) -> list:
    """
    Do toc do phan giai DNS.
    [PATCHED] Chay song song (concurrent) thay vi tuan tu blocking.
    Neu 2/4 server bi timeout, luong nen se khong bi dong bang 30 giay nua.
    """
    if servers is None:
        servers = [
            ("Google",     "8.8.8.8"),
            ("Cloudflare", "1.1.1.1"),
            ("OpenDNS",    "208.67.222.222"),
            ("Quad9",      "9.9.9.9"),
        ]
    test_domain = "www.google.com"

    def _bench_one(name_ip):
        name, ip = name_ip
        times = []
        for _ in range(3):
            t0 = time.perf_counter()
            ok_, _, _ = run_cmd(
                ["nslookup", test_domain, ip], shell=False, timeout=5
            )
            elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
            if ok_:
                times.append(elapsed_ms)
        avg = round(sum(times) / len(times), 1) if times else None
        return {
            "name":   name,
            "server": ip,
            "avg_ms": avg,
            "ok":     avg is not None,
        }

    from concurrent.futures import ThreadPoolExecutor, as_completed
    results = []
    with ThreadPoolExecutor(max_workers=len(servers)) as pool:
        futures = {pool.submit(_bench_one, s): s for s in servers}
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as exc:
                name, ip = futures[future]
                results.append({"name": name, "server": ip, "avg_ms": None, "ok": False})
                log(f"DNS benchmark loi ({name}): {exc}", "error")

    results.sort(key=lambda x: x["avg_ms"] or 99999)
    return results

def apply_best_dns(server_ip: str):
    """
    Thiet lap DNS cho tat ca adapter dang hoat dong.
    [PATCHED] Chong Command Injection bang Regex validate truoc,
    dung PowerShell Set-DnsClientServerAddress thay vi netsh+shell=True cu.
    """
    section(f"Ap dung DNS bao mat: {server_ip}")

    # ── Validate IP truoc khi truyen vao bat ky lenh nao ─────────────────────
    if not re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", server_ip):
        err("Dia chi IP DNS khong hop le! Tu choi thuc thi de bao ve he thong.")
        return

    octets = server_ip.split(".")
    if not all(0 <= int(o) <= 255 for o in octets):
        err("Dia chi IP DNS nam ngoai pham vi hop le (0-255). Tu choi thuc thi.")
        return

    # ── Win8+: dung PowerShell cmdlet hien dai, an toan ─────────────────────
    if IS_WIN8_PLUS:
        ps_script = (
            f"Get-NetAdapter | Where-Object {{$_.Status -eq 'Up'}} | "
            f"Set-DnsClientServerAddress "
            f"-ServerAddresses '{server_ip}', '8.8.4.4' "
            f"-ErrorAction SilentlyContinue"
        )
        ok_, _, stderr = ps(ps_script, timeout=30)
        if ok_:
            ok(f"DNS da duoc dong bo hoa thanh cong sang: {server_ip} (backup: 8.8.4.4)")
        else:
            warn(f"PowerShell Set-DnsClientServerAddress gap loi: {stderr}. Thu fallback netsh...")
            _apply_dns_netsh_fallback(server_ip)
    else:
        # Win7 fallback
        _apply_dns_netsh_fallback(server_ip)

    # Flush DNS cache – goi truc tiep, KHONG qua shell
    subprocess.run(["ipconfig", "/flushdns"], capture_output=True, check=False)
    ok("DNS cache da duoc xoa")

def _apply_dns_netsh_fallback(server_ip: str):
    """
    Fallback cho Win7 hoac khi PowerShell that bai.
    Truyen tham so dang mang (list) de tranh shell injection.
    Chi goi ham nay sau khi da validate server_ip bang Regex.
    """
    # Lay danh sach interface qua netsh voi tham so mang (shell=False)
    ok_, out, _ = run_cmd(
        ["netsh", "interface", "show", "interface"],
        shell=False, timeout=15
    )
    interfaces = []
    for line in (out or "").splitlines():
        m = re.search(r"Connected\s+.*?\s+(\S.+)$", line)
        if m:
            iface = m.group(1).strip()
            if iface:
                interfaces.append(iface)
    if not interfaces:
        interfaces = ["Wi-Fi", "Ethernet", "Local Area Connection"]

    for iface in interfaces:
        # Truyen tung tham so rieng biet (list) – KHONG noi chuoi, KHONG shell=True
        run_cmd(
            ["netsh", "interface", "ip", "set", "dns",
             f"name={iface}", "static", server_ip],
            shell=False, timeout=15
        )
        run_cmd(
            ["netsh", "interface", "ip", "add", "dns",
             f"name={iface}", "8.8.4.4", "index=2"],
            shell=False, timeout=15
        )
    ok(f"DNS (netsh fallback) da duoc doi thanh {server_ip} tren {len(interfaces)} adapter")

# =============================================================================
#  DRIVER CHECKER  (v7)
# =============================================================================
def check_outdated_drivers(days_old: int = 365) -> list:
    """
    Liet ke driver co DriverDate cu hon {days_old} ngay.
    Tra ve list dict {name, date, provider, version}.
    """
    section(f"Driver Checker (driver cu hon {days_old} ngay)")
    info("Dang quet driver... (co the mat 10-20 giay)")
    raw = wmic(
        "path Win32_PnPSignedDriver get "
        "DeviceName,DriverDate,DriverVersion,DriverProviderName /value",
        timeout=60
    )
    drivers = []
    cur = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            if cur.get("DeviceName") and cur.get("DriverDate"):
                cur_copy = dict(cur)
                try:
                    date_str = cur_copy["DriverDate"][:8]  # YYYYMMDD
                    drv_date = datetime.strptime(date_str, "%Y%m%d").date()
                    age_days = (date.today() - drv_date).days
                    if age_days > days_old:
                        cur_copy["age_days"] = age_days
                        cur_copy["date_fmt"] = drv_date.strftime("%Y-%m-%d")
                        drivers.append(cur_copy)
                except Exception:
                    pass
            cur = {}
        elif "=" in line:
            k, _, v = line.partition("=")
            cur[k.strip()] = v.strip()

    drivers.sort(key=lambda x: x.get("age_days", 0), reverse=True)
    if drivers:
        for d in drivers[:15]:
            warn(f"{d.get('DeviceName','?')[:50]:<50}  {d.get('date_fmt','?')}  ({d.get('age_days','?')}d old)")
    else:
        ok("Khong phat hien driver nao qua cu.")
    info(f"Tong {len(drivers)} driver cu hon {days_old} ngay")
    return drivers

# =============================================================================
#  BEFORE / AFTER PANEL STATE  (v7)
# =============================================================================
class BeforeAfterTracker:
    """Luu tru dung luong truoc/sau moi phien de hien thi so sanh."""
    def __init__(self):
        self.path = os.path.join(APP_DIR, "before_after.json")
        self._load()

    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                self._data = json.load(f)
        except Exception:
            self._data = {"history": []}

    def _save(self):
        os.makedirs(APP_DIR, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def snapshot_before(self):
        self._before = {}
        for drive in detect_fixed_drives()[:4]:
            try:
                _, _, free = shutil.disk_usage(f"{drive}:\\")
                self._before[drive] = free
            except Exception:
                pass

    def snapshot_after(self, label: str = ""):
        if not hasattr(self, "_before"):
            return
        entry = {
            "ts":     datetime.now().isoformat(timespec="seconds"),
            "label":  label,
            "drives": {},
        }
        for drive in list(self._before.keys()):
            try:
                _, _, free = shutil.disk_usage(f"{drive}:\\")
                gained = free - self._before[drive]
                entry["drives"][drive] = {
                    "before_free": self._before[drive],
                    "after_free":  free,
                    "gained":      gained,
                }
            except Exception:
                pass
        self._data.setdefault("history", []).append(entry)
        # Keep last 20 records
        self._data["history"] = self._data["history"][-20:]
        self._save()
        return entry

    def last_entry(self):
        h = self._data.get("history", [])
        return h[-1] if h else None

    def all_history(self):
        return list(reversed(self._data.get("history", [])))

_ba_tracker = BeforeAfterTracker()

# =============================================================================
#  THEME ENGINE  (v7 – Dark / Light toggle)
# =============================================================================
THEMES = {
    "dark": {
        "bg":        "#0d1117",
        "panel":     "#161b22",
        "border":    "#30363d",
        "fg":        "#e6edf3",
        "fg_dim":    "#8b949e",
        "accent":    "#58a6ff",
        "accent2":   "#a371f7",
        "green":     "#3fb950",
        "yellow":    "#d29922",
        "red":       "#f85149",
        "log_bg":    "#0a0f1e",
        "entry_bg":  "#0d1117",
    },
    "light": {
        "bg":        "#ffffff",
        "panel":     "#f6f8fa",
        "border":    "#d0d7de",
        "fg":        "#1f2328",
        "fg_dim":    "#636c76",
        "accent":    "#0969da",
        "accent2":   "#8250df",
        "green":     "#1a7f37",
        "yellow":    "#9a6700",
        "red":       "#d1242f",
        "log_bg":    "#f6f8fa",
        "entry_bg":  "#ffffff",
    },
}

# =============================================================================
#  I18N – MULTI-LANGUAGE SUPPORT  (v8)
# =============================================================================
_STRINGS = {
    "vi": {
        "app_ready":        "San sang",
        "running":          "Dang chay...",
        "done":             "Hoan thanh",
        "confirm_extreme":  "Ban co chac muon chay profile manh nay?",
        "kill_confirm":     "Kill process '{name}' (PID {pid})?",
        "no_backup":        "Khong co backup nao.",
        "settings_saved":   "Settings da duoc luu",
        "restart_needed":   "Can restart may de hoan tat.",
        "tab_optimize":     "⚡ Optimize",
        "tab_cleaner":      "🧹 Cleaner",
        "tab_tools":        "🔧 Tools",
        "tab_processes":    "📊 Processes",
        "tab_network":      "🌐 Network",
        "tab_startup":      "🚀 Startup",
        "tab_schedule":     "⏰ Schedule",
        "tab_benchmark":    "📈 Benchmark",
        "tab_history":      "📋 History",
        "tab_tweaks":       "🎛 Tweaks",
        "tab_settings":     "⚙ Settings",
        "tab_info":         "ℹ Info",
    },
    "en": {
        "app_ready":        "Ready",
        "running":          "Running...",
        "done":             "Done",
        "confirm_extreme":  "Run this aggressive profile?",
        "kill_confirm":     "Kill process '{name}' (PID {pid})?",
        "no_backup":        "No backup found.",
        "settings_saved":   "Settings saved",
        "restart_needed":   "Restart required to complete.",
        "tab_optimize":     "⚡ Optimize",
        "tab_cleaner":      "🧹 Cleaner",
        "tab_tools":        "🔧 Tools",
        "tab_processes":    "📊 Processes",
        "tab_network":      "🌐 Network",
        "tab_startup":      "🚀 Startup",
        "tab_schedule":     "⏰ Schedule",
        "tab_benchmark":    "📈 Benchmark",
        "tab_history":      "📋 History",
        "tab_tweaks":       "🎛 Tweaks",
        "tab_settings":     "⚙ Settings",
        "tab_info":         "ℹ Info",
    },
}
_LANG = "vi"

def t(key: str, **kwargs) -> str:
    """Tra ve chuoi da dich. Fallback sang 'vi' neu key khong ton tai."""
    text = _STRINGS.get(_LANG, {}).get(key) or _STRINGS["vi"].get(key, key)
    return text.format(**kwargs) if kwargs else text

def set_language(lang: str):
    global _LANG
    if lang in _STRINGS:
        _LANG = lang

# =============================================================================
#  LIGHTWEIGHT ENCRYPTION  (v8 – bao ve backup.json bang XOR+base64)
# =============================================================================
import base64

_DEFAULT_KEY = b"WinOptimizer8Key"

def _xor_bytes(data: bytes, key: bytes) -> bytes:
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))

def encrypt_backup(plaintext: str, key: bytes = _DEFAULT_KEY) -> str:
    """Ma hoa JSON text -> base64 string."""
    return base64.b64encode(_xor_bytes(plaintext.encode("utf-8"), key)).decode("ascii")

def decrypt_backup(ciphertext: str, key: bytes = _DEFAULT_KEY) -> str:
    """Giai ma base64 string -> JSON text."""
    return _xor_bytes(base64.b64decode(ciphertext.encode("ascii")), key).decode("utf-8")

def save_backup_encrypted(data: dict, key: bytes = _DEFAULT_KEY):
    """Luu backup.json ma hoa."""
    ensure_dirs()
    plaintext = json.dumps(data, ensure_ascii=False, indent=2)
    enc_path  = BACKUP_JSON + ".enc"
    with open(enc_path, "w", encoding="ascii") as f:
        f.write(encrypt_backup(plaintext, key))

def load_backup_encrypted(key: bytes = _DEFAULT_KEY) -> dict:
    enc_path = BACKUP_JSON + ".enc"
    if not os.path.exists(enc_path):
        return load_backup()
    try:
        with open(enc_path, "r", encoding="ascii") as f:
            ciphertext = f.read()
        plaintext = decrypt_backup(ciphertext, key)
        data = json.loads(plaintext)
        base = _default_backup()
        base.update(data or {})
        return base
    except Exception:
        return load_backup()

# =============================================================================
#  PYTHON BENCHMARK  (v8 – CPU / RAM / Disk, khong can thu vien ngoai)
# =============================================================================
import hashlib
import tempfile

def benchmark_cpu(duration_s: float = 3.0) -> dict:
    """Do toc do tinh toan CPU bang SHA-256 hash loop."""
    section("CPU Benchmark")
    info(f"Dang chay CPU benchmark trong {duration_s}s...")
    count   = 0
    payload = b"WinOptimizer_CPU_Bench_v8" * 16
    t_end   = time.perf_counter() + duration_s
    while time.perf_counter() < t_end:
        hashlib.sha256(payload).digest()
        count += 1
    rate = round(count / duration_s / 1000, 1)
    ok(f"CPU: {rate}K SHA-256/s trong {duration_s}s ({count:,} hashes)")
    return {"hashes_per_sec": count / duration_s, "k_per_sec": rate, "duration": duration_s}

def benchmark_ram(size_mb: int = 128) -> dict:
    """Do bang cach doc/ghi mot mang bytes trong RAM."""
    section("RAM Benchmark")
    info(f"Dang test RAM R/W voi {size_mb}MB...")
    size_b = size_mb * (1 << 20)
    try:
        # Write
        t0   = time.perf_counter()
        buf  = bytearray(size_b)
        for i in range(0, size_b, 4096):
            buf[i] = i & 0xFF
        write_s = time.perf_counter() - t0
        # Read
        t1 = time.perf_counter()
        chk = 0
        for i in range(0, size_b, 4096):
            chk += buf[i]
        read_s = time.perf_counter() - t1
        del buf
        write_mbps = round(size_mb / write_s, 1)
        read_mbps  = round(size_mb / read_s,  1)
        ok(f"RAM Write: {write_mbps} MB/s  |  Read: {read_mbps} MB/s")
        return {"write_mbps": write_mbps, "read_mbps": read_mbps, "size_mb": size_mb}
    except MemoryError:
        warn(f"Khong du RAM cho {size_mb}MB test. Thu voi 32MB.")
        return benchmark_ram(32)

def benchmark_disk(drive: str = None, size_mb: int = 64) -> dict:
    """Do toc do ghi/doc dia bang file tam."""
    section("Disk Benchmark")
    if drive is None:
        drive = SYSDRIVE
    test_path = os.path.join(drive + "\\", "winopt_bench_tmp.bin")
    size_b    = size_mb * (1 << 20)
    chunk     = b"\xAB\xCD\xEF\x01" * 1024  # 4KB chunk
    info(f"Dang test disk I/O tren {drive}: ({size_mb}MB)...")
    try:
        # Sequential write
        t0 = time.perf_counter()
        with open(test_path, "wb") as f:
            written = 0
            while written < size_b:
                to_write = min(len(chunk), size_b - written)
                f.write(chunk[:to_write])
                written += to_write
            f.flush()
            os.fsync(f.fileno())
        write_s    = time.perf_counter() - t0
        write_mbps = round(size_mb / write_s, 1)

        # Sequential read
        t1 = time.perf_counter()
        with open(test_path, "rb") as f:
            while f.read(len(chunk)):
                pass
        read_s    = time.perf_counter() - t1
        read_mbps = round(size_mb / read_s, 1)

        ok(f"Disk ({drive}:) Write: {write_mbps} MB/s  |  Read: {read_mbps} MB/s")
        return {"write_mbps": write_mbps, "read_mbps": read_mbps, "drive": drive, "size_mb": size_mb}
    except Exception as exc:
        warn(f"Disk benchmark loi: {exc}")
        return {"write_mbps": 0, "read_mbps": 0, "drive": drive, "size_mb": size_mb}
    finally:
        try:
            os.remove(test_path)
        except Exception:
            pass

def run_full_benchmark(size_mb_ram: int = 128, size_mb_disk: int = 64) -> dict:
    """Chay CPU + RAM + Disk benchmark, tra ve ket qua tong hop."""
    results = {}
    results["cpu"]  = benchmark_cpu(3.0)
    results["ram"]  = benchmark_ram(size_mb_ram)
    drives = detect_fixed_drives()[:2]
    results["disk"] = {}
    for drv in drives:
        results["disk"][drv] = benchmark_disk(drv, size_mb_disk)
    return results

# =============================================================================
#  STARTUP IMPACT ANALYZER  (v8 – doc EventLog ID 100 = boot duration)
# =============================================================================
def get_startup_boot_time() -> dict:
    """
    Doc thoi gian boot Windows tu EventLog (EventID 100, Source Diagnostics-Performance).
    Tra ve dict {last_boot_ms, avg_boot_ms, samples}.
    """
    info("Doc thoi gian boot tu EventLog (EventID 100)...")
    if not IS_WIN8_PLUS:
        info("Win7: doc tu registry SystemBootDevice thay the.")
        return {"last_boot_ms": None, "avg_boot_ms": None, "samples": 0}

    ok_, out, _ = ps(
        'try { '
        '$events = Get-WinEvent -FilterHashtable '
        '@{LogName="Microsoft-Windows-Diagnostics-Performance/Operational"; Id=100} '
        '-MaxEvents 10 -ErrorAction Stop; '
        '$times = $events | ForEach-Object { '
        '($_.Properties | Where-Object {$_.Value -is [int]}) | '
        'Select-Object -First 1 -ExpandProperty Value }; '
        '$times -join "," '
        '} catch { "ERROR" }',
        timeout=20
    )
    if not ok_ or "ERROR" in (out or ""):
        return {"last_boot_ms": None, "avg_boot_ms": None, "samples": 0}

    times = []
    for part in (out or "").split(","):
        part = part.strip()
        try:
            v = int(part)
            if 1000 < v < 300000:   # sanity check: 1s – 5min
                times.append(v)
        except Exception:
            pass

    if not times:
        return {"last_boot_ms": None, "avg_boot_ms": None, "samples": 0}

    return {
        "last_boot_ms": times[0],
        "avg_boot_ms":  round(sum(times) / len(times)),
        "samples":      len(times),
        "all_ms":       times,
    }

# =============================================================================
#  DUPLICATE FILE FINDER  (v8 – MD5 hash)
# =============================================================================
def find_duplicate_files(root: str = None, min_size_kb: int = 100,
                          max_files: int = 50000) -> dict:
    """
    Quet root de tim file trung lap (cung MD5 hash).
    Tra ve dict {hash: [path1, path2, ...]}, chi giu nhung hash co >= 2 file.
    """
    section(f"Duplicate File Finder (>= {min_size_kb}KB)")
    if root is None:
        root = USERPROFILE or os.path.expanduser("~")
    info(f"Dang quet: {root} ...")

    hashes: dict = {}
    scanned = 0
    min_size = min_size_kb * 1024

    for dirpath, _, files in os.walk(root):
        # Skip system dirs
        skip_parts = {".git", "node_modules", "Windows", "$Recycle.Bin",
                      "System Volume Information", "AppData\\Local\\Microsoft\\Windows\\INetCache"}
        if any(sp.lower() in dirpath.lower() for sp in skip_parts):
            continue
        for fname in files:
            if scanned >= max_files:
                break
            fp = os.path.join(dirpath, fname)
            try:
                sz = os.path.getsize(fp)
                if sz < min_size:
                    continue
                h = hashlib.md5(open(fp, "rb").read(65536)).hexdigest()  # first 64KB
                hashes.setdefault(h, []).append((fp, sz))
                scanned += 1
            except (PermissionError, OSError):
                pass

    dupes = {h: paths for h, paths in hashes.items() if len(paths) >= 2}
    total_wasted = sum(
        sum(sz for _, sz in paths[1:])   # all but first copy
        for paths in dupes.values()
    )
    info(f"Quet {scanned:,} files | Tim thay {len(dupes)} nhom trung lap | "
         f"Dung luong lua: ~{fmt_bytes(total_wasted)}")
    for h, paths in list(dupes.items())[:10]:
        ok(f"  [{fmt_bytes(paths[0][1])}] {len(paths)} ban sao:")
        for fp, sz in paths[:3]:
            info(f"    {fp}")
    return dupes

# =============================================================================
#  EMPTY FOLDER CLEANER  (v8)
# =============================================================================
def remove_empty_folders(root: str = None) -> int:
    """Xoa toan bo thu muc rong duoi root. Tra ve so luong da xoa."""
    section("Empty Folder Cleaner")
    if root is None:
        root = USERPROFILE or os.path.expanduser("~")
    info(f"Dang quet: {root} ...")
    removed = 0
    skip_roots = {"windows", "program files", "program files (x86)"}
    for dirpath, dirs, files in os.walk(root, topdown=False):
        if any(s in dirpath.lower() for s in skip_roots):
            continue
        if not files and not dirs:
            try:
                os.rmdir(dirpath)
                removed += 1
            except Exception:
                pass
        elif not files:
            # Check if all subdirs were just removed
            remaining = [d for d in dirs if os.path.exists(os.path.join(dirpath, d))]
            if not remaining:
                try:
                    os.rmdir(dirpath)
                    removed += 1
                except Exception:
                    pass
    ok(f"Da xoa {removed} thu muc rong")
    return removed

# =============================================================================
#  PREFETCH ANALYZER  (v8 – xem danh sach file .pf)
# =============================================================================
def analyze_prefetch() -> list:
    """Liet ke cac file .pf trong Windows Prefetch folder."""
    section("Prefetch Analyzer")
    pf_dir = os.path.join(WINDIR, "Prefetch")
    if not os.path.isdir(pf_dir):
        info("Prefetch folder khong ton tai hoac bi tat.")
        return []
    entries = []
    for fname in os.listdir(pf_dir):
        if not fname.upper().endswith(".PF"):
            continue
        fp = os.path.join(pf_dir, fname)
        try:
            sz  = os.path.getsize(fp)
            mtime = datetime.fromtimestamp(os.path.getmtime(fp))
            app_name = fname.split("-")[0].replace(".EXE", "").title()
            entries.append({
                "file":     fname,
                "app":      app_name,
                "size_kb":  sz // 1024,
                "last_run": mtime.strftime("%Y-%m-%d %H:%M"),
            })
        except Exception:
            pass
    entries.sort(key=lambda x: x["last_run"], reverse=True)
    info(f"Tim thay {len(entries)} Prefetch entries")
    for e in entries[:10]:
        info(f"  {e['app']:<30} {e['last_run']}  ({e['size_kb']}KB)")
    return entries

# =============================================================================
#  AUTO-PROFILE BY TIME  (v8 – tu dong chuyen profile theo gio trong ngay)
# =============================================================================
_TIME_PROFILE_DEFAULTS = {
    "day_start":    8,    # 08:00 – chuyen sang Everyday
    "night_start":  22,   # 22:00 – chuyen sang Laptop/Gaming
    "gaming_start": 18,   # 18:00 – chuyen sang Gaming Plus
}

def auto_profile_by_time(settings: dict = None):
    """
    Kiem tra gio hien tai va ap dung profile phu hop:
      08:00-18:00 -> Everyday Safe
      18:00-22:00 -> Gaming Plus
      22:00-08:00 -> Laptop Turbo (tiet kiem dien)
    """
    if settings is None:
        settings = load_settings()
    tp     = settings.get("time_profiles", _TIME_PROFILE_DEFAULTS)
    hour   = datetime.now().hour
    d_s    = tp.get("day_start",    8)
    g_s    = tp.get("gaming_start", 18)
    n_s    = tp.get("night_start",  22)

    if d_s <= hour < g_s:
        profile = "everyday"
        name    = "Everyday Safe"
    elif g_s <= hour < n_s:
        profile = "gaming_plus"
        name    = "Gaming Plus"
    else:
        profile = "laptop"
        name    = "Laptop Turbo"

    info(f"Auto-profile theo gio {hour:02d}:xx -> {name}")
    apply_power_profile(profile)
    optimize_gaming_registry()
    ok(f"Auto-profile applied: {name}")

# =============================================================================
#  INDIVIDUAL TWEAK REGISTRY  (v8 – danh sach cho Tweaks tab)
# =============================================================================
ALL_TWEAKS = [
    # (key, label, hive, path, name, value_on, value_off, regtype, win_min)
    # win_min: 7=Win7+, 10=Win10+, 11=Win11+
    ("game_mode",      "Game Mode (Win10+)",             "HKCU", r"SOFTWARE\Microsoft\GameBar",  "AutoGameModeEnabled",       1, 0, REG_DWORD, 10),
    ("game_dvr",       "Disable Game DVR",               "HKCU", r"System\GameConfigStore",       "GameDVR_Enabled",           0, 1, REG_DWORD, 10),
    ("transparency",   "Disable Transparency",           "HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Themes\Personalize", "EnableTransparency", 0, 1, REG_DWORD, 10),
    ("taskbar_anim",   "Disable Taskbar Animations",     "HKCU", r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced", "TaskbarAnimations", 0, 1, REG_DWORD, 7),
    ("win_anim",       "Disable Window Animations",      "HKCU", r"Control Panel\Desktop\WindowMetrics", "MinAnimate",            "0","1", REG_SZ,   7),
    ("menu_delay",     "Menu Show Delay = 20ms",         "HKCU", r"Control Panel\Desktop",        "MenuShowDelay",             "20","400",REG_SZ, 7),
    ("autoend_tasks",  "Auto End Hung Tasks",            "HKCU", r"Control Panel\Desktop",        "AutoEndTasks",              "1","0", REG_SZ,   7),
    ("mouse_accel",    "Disable Mouse Acceleration",     "HKCU", r"Control Panel\Mouse",          "MouseSpeed",                "0","1", REG_SZ,   7),
    ("ntfs_last_acc",  "NTFS Disable Last Access Update","HKLM", r"SYSTEM\CurrentControlSet\Control\FileSystem", "NtfsDisableLastAccessUpdate", 1, 0, REG_DWORD, 7),
    ("pri_sep",        "Foreground App Priority Boost",  "HKLM", r"SYSTEM\CurrentControlSet\Control\PriorityControl", "Win32PrioritySeparation", 38, 2, REG_DWORD, 7),
    ("sys_resp",       "MMCSS SystemResponsiveness=10",  "HKLM", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile", "SystemResponsiveness", 10, 20, REG_DWORD, 7),
    ("net_throttle",   "Disable Network Throttling",     "HKLM", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile", "NetworkThrottlingIndex", 0xffffffff, 10, REG_DWORD, 7),
    ("tcp_timewait",   "TCP TimeWait = 30s",             "HKLM", r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters", "TcpTimedWaitDelay", 30, 240, REG_DWORD, 7),
    ("bing_search",    "Disable Bing Search (Win10+)",   "HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Search", "BingSearchEnabled", 0, 1, REG_DWORD, 10),
    ("cortana",        "Disable Cortana (Win10+)",       "HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Search", "CortanaConsent", 0, 1, REG_DWORD, 10),
    ("hags",           "Hardware GPU Scheduling (HAGS)", "HKLM", r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers", "HwSchMode", 2, 1, REG_DWORD, 10),
    ("explorer_sep",   "Explorer Separate Process",      "HKCU", r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced", "SeparateProcess", 1, 0, REG_DWORD, 7),
    ("kb_speed",       "Keyboard Speed = Max",           "HKCU", r"Control Panel\Keyboard",       "KeyboardSpeed",             "31","31",REG_SZ, 7),
    ("kb_delay",       "Keyboard Delay = 0",             "HKCU", r"Control Panel\Keyboard",       "KeyboardDelay",             "0","1", REG_SZ,  7),
    ("widgets_w11",    "Disable Widgets Bar (Win11)",    "HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Advanced", "TaskbarDa", 0, 1, REG_DWORD, 11),
    ("start_reco_w11", "Disable Start Recommendations (Win11)", "HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Advanced", "Start_IrisRecommendations", 0, 1, REG_DWORD, 11),
]

def apply_tweak(key: str, enable: bool) -> bool:
    """Ap dung mot tweak cu the theo key. enable=True: bat, False: tat/phuc hoi."""
    for item in ALL_TWEAKS:
        if item[0] != key:
            continue
        _, label, hive, path, name, val_on, val_off, regtype, win_min = item
        # Check Windows version
        if win_min >= 11 and not IS_WIN11:
            warn(f"{label}: chi ho tro Win11. Bo qua.")
            return False
        if win_min >= 10 and not IS_WIN10_PLUS:
            warn(f"{label}: chi ho tro Win10+. Bo qua.")
            return False
        value = val_on if enable else val_off
        ok_, _, _ = reg_add(hive, path, name, value, regtype)
        if ok_:
            ok(f"{'ON' if enable else 'OFF'}: {label}")
        else:
            warn(f"That bai: {label}")
        return ok_
    warn(f"Khong tim thay tweak: {key}")
    return False

def get_tweak_current_state(key: str):
    """Doc gia tri registry hien tai cua tweak. Tra ve True/False/None."""
    for item in ALL_TWEAKS:
        if item[0] != key:
            continue
        _, label, hive, path, name, val_on, val_off, regtype, _ = item
        exists, _, cur_val = reg_query(hive, path, name)
        if not exists:
            return None
        try:
            if regtype == REG_DWORD:
                return int(cur_val, 16) == int(str(val_on)) if "0x" in str(cur_val).lower() else int(cur_val) == int(str(val_on))
            else:
                return str(cur_val).strip() == str(val_on).strip()
        except Exception:
            return None
    return None

# =============================================================================
#  ENHANCED HTML REPORT v3  (v8 – CPU/RAM gauge + Before/After bar chart)
# =============================================================================
def generate_html_report_v3(results: list, sysinfo: dict, duration_s: float,
                              profile_name: str = "",
                              bench_results: dict = None,
                              ba_entry: dict = None) -> str:
    ts      = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ts_safe = datetime.now().strftime("%Y%m%d_%H%M%S")
    total_freed   = sum(r.freed   for r in results if hasattr(r, "freed"))
    total_deleted = sum(r.deleted for r in results if hasattr(r, "freed"))

    rows = "".join(
        f"<tr><td>{r.name}</td><td>{fmt_bytes(r.freed)}</td><td>{r.deleted:,}</td></tr>\n"
        for r in results if hasattr(r, "freed")
    )

    # Before/After bars
    ba_html = ""
    if ba_entry:
        ba_html = "<h2>Before / After Disk Space</h2><div class='ba-grid'>"
        for drive, d in ba_entry.get("drives", {}).items():
            before = d.get("before_free", 0)
            after  = d.get("after_free",  0)
            gained = max(d.get("gained", 0), 0)
            try:
                _, _, total = shutil.disk_usage(f"{drive}:\\")
            except Exception:
                total = max(before, after, 1)
            b_pct  = int(before * 100 / total) if total else 0
            a_pct  = int(after  * 100 / total) if total else 0
            ba_html += f"""
            <div class='ba-card'>
              <div class='ba-title'>Drive {drive}:</div>
              <div class='ba-row'><span>Before</span>
                <div class='bar-outer'><div class='bar-fill bar-before' style='width:{b_pct}%'></div></div>
                <span>{fmt_bytes(before)}</span></div>
              <div class='ba-row'><span>After &nbsp;</span>
                <div class='bar-outer'><div class='bar-fill bar-after'  style='width:{a_pct}%'></div></div>
                <span>{fmt_bytes(after)}</span></div>
              <div class='ba-gained'>+ {fmt_bytes(gained)} freed</div>
            </div>"""
        ba_html += "</div>"

    # Benchmark section
    bench_html = ""
    if bench_results:
        cpu  = bench_results.get("cpu", {})
        ram  = bench_results.get("ram", {})
        disk = bench_results.get("disk", {})
        bench_html = f"""
        <h2>Benchmark Results</h2>
        <div style='display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px'>
          <div class='card'>
            <div>CPU (SHA-256)</div>
            <div class='big'>{cpu.get('k_per_sec','?')}K/s</div>
            <div style='color:#8b949e;font-size:.85em'>{cpu.get('duration','?')}s test</div>
          </div>
          <div class='card'>
            <div>RAM Bandwidth</div>
            <div class='big'>{ram.get('read_mbps','?')}<span style='font-size:.5em'> MB/s R</span></div>
            <div style='color:#8b949e;font-size:.85em'>Write: {ram.get('write_mbps','?')} MB/s</div>
          </div>
          {"".join(f'''<div class='card'><div>Disk {drv}:</div>
            <div class='big'>{d.get('read_mbps','?')}<span style='font-size:.5em'> MB/s R</span></div>
            <div style='color:#8b949e;font-size:.85em'>Write: {d.get('write_mbps','?')} MB/s</div></div>'''
            for drv, d in disk.items())}
        </div>"""

    gpus_html = "".join(
        f"<li>{g['name']} | Driver {g['driver']} | VRAM {g['vram_mb']}MB</li>"
        for g in sysinfo.get("gpus", [])
    )

    ram_pct = int(sysinfo.get("ram_gb", 0) * 100 / max(sysinfo.get("ram_gb", 1), 1))
    free_c  = sysinfo.get("free_c_gb", 0)
    tot_c   = sysinfo.get("total_c_gb", 1)
    disk_pct = int((tot_c - free_c) * 100 / max(tot_c, 1))

    html = textwrap.dedent(f"""
    <!DOCTYPE html>
    <html lang="vi">
    <head>
    <meta charset="UTF-8">
    <title>{APP_NAME} v{APP_VERSION} – Report {ts}</title>
    <style>
      *{{box-sizing:border-box}} body{{font-family:'Segoe UI',Arial,sans-serif;background:#0d1117;color:#e6edf3;margin:0;padding:24px}}
      h1{{color:#58a6ff;border-bottom:2px solid #21262d;padding-bottom:10px;margin-bottom:6px}}
      h2{{color:#a371f7;margin-top:28px;margin-bottom:10px}}
      table{{border-collapse:collapse;width:100%;margin-top:10px}}
      th{{background:#161b22;color:#58a6ff;padding:10px;text-align:left;font-weight:600}}
      td{{padding:8px 10px;border-bottom:1px solid #21262d}}
      tr:hover td{{background:#161b22}}
      .card{{background:#161b22;border-radius:10px;padding:16px;border:1px solid #21262d}}
      .big{{font-size:2em;font-weight:700;color:#58a6ff;line-height:1.1}}
      ul{{padding-left:18px}} li{{margin:4px 0}}
      .grid3{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px;margin-bottom:16px}}
      .ba-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px}}
      .ba-card{{background:#161b22;border-radius:8px;padding:14px;border:1px solid #21262d}}
      .ba-title{{font-weight:700;color:#58a6ff;margin-bottom:8px}}
      .ba-row{{display:flex;align-items:center;gap:8px;margin:4px 0;font-size:.85em}}
      .ba-row span:first-child{{width:52px;color:#8b949e}}
      .bar-outer{{flex:1;height:10px;background:#21262d;border-radius:5px;overflow:hidden}}
      .bar-fill{{height:100%;border-radius:5px}}
      .bar-before{{background:#d29922}}
      .bar-after{{background:#3fb950}}
      .ba-gained{{color:#3fb950;font-weight:700;margin-top:6px;font-size:.9em}}
      footer{{color:#30363d;font-size:.75em;margin-top:32px}}
    </style>
    </head>
    <body>
    <h1>🖥 {APP_NAME} <small style='font-size:.45em;color:#a371f7'>{APP_SUBTITLE}</small></h1>
    <p style='color:#8b949e'>{ts} &nbsp;·&nbsp; {duration_s:.1f}s &nbsp;·&nbsp; {profile_name or 'Manual Run'}</p>

    <div class='grid3'>
      <div class='card'><div style='color:#8b949e'>Freed</div><div class='big'>{fmt_bytes(total_freed)}</div></div>
      <div class='card'><div style='color:#8b949e'>Files Deleted</div><div class='big'>{total_deleted:,}</div></div>
      <div class='card'><div style='color:#8b949e'>Free (C:)</div><div class='big'>{free_c} GB</div></div>
    </div>

    {ba_html}

    <h2>Cleanup Details</h2>
    <table><tr><th>Module</th><th>Freed</th><th>Files</th></tr>{rows}</table>

    {bench_html}

    <h2>System Information</h2>
    <div class='card'>
      <ul>
        <li><b>OS:</b> {sysinfo.get('os_caption','?')} | Build {sysinfo.get('os_build','?')}</li>
        <li><b>CPU:</b> {sysinfo.get('cpu_name','?')} | {sysinfo.get('cpu_cores','?')}c/{sysinfo.get('cpu_logical','?')}t @ {sysinfo.get('cpu_mhz','?')}MHz</li>
        <li><b>RAM:</b> {sysinfo.get('ram_gb','?')} GB</li>
        <li><b>GPU:</b><ul>{gpus_html}</ul></li>
        <li><b>Disk C:</b> {tot_c}GB total | {free_c}GB free ({100-disk_pct}% used)</li>
      </ul>
    </div>
    <footer>Generated by {APP_NAME} v{APP_VERSION} &nbsp;|&nbsp; {ts}</footer>
    </body></html>
    """).strip()

    path = os.path.join(REPORT_DIR, f"report_{ts_safe}.html")
    os.makedirs(REPORT_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    ok(f"HTML Report v3: {path}")
    return path

# =============================================================================
#  REAL-TIME SYSTEM METRICS  (v9 – CPU / RAM polling via wmic/ctypes)
# =============================================================================
import collections

_METRIC_HISTORY_LEN = 60   # seconds of history

class MetricsCollector:
    """
    Thu thap CPU% va RAM% theo thoi gian thuc.
    Dung wmic hoac ctypes (PROCESS_MEMORY_COUNTERS) tuy theo platform.
    """
    def __init__(self, maxlen: int = _METRIC_HISTORY_LEN):
        self.cpu_history  = collections.deque([0.0] * maxlen, maxlen=maxlen)
        self.ram_history  = collections.deque([0.0] * maxlen, maxlen=maxlen)
        self.net_sent     = collections.deque([0.0] * maxlen, maxlen=maxlen)
        self.net_recv     = collections.deque([0.0] * maxlen, maxlen=maxlen)
        self._prev_cpu_idle = None
        self._prev_cpu_total = None
        self._prev_net_sent = 0
        self._prev_net_recv = 0
        self._lock = threading.Lock()
        self._running = False
        self._thread  = None

    # ── CPU % via NtQuerySystemInformation / GetSystemTimes (khong sinh tien trinh con) ──
    def _get_cpu_pct(self) -> float:
        """
        [PATCHED] Dung kernel32.GetSystemTimes thay vi wmic (non-blocking, ~0ms, Win11 safe).
        wmic trong real-time loop lam block 1-3 giay moi lan goi.
        """
        try:
            import ctypes
            class FILETIME(ctypes.Structure):
                _fields_ = [("dwLowDateTime", ctypes.c_ulong),
                             ("dwHighDateTime", ctypes.c_ulong)]
            idle   = FILETIME()
            kernel = FILETIME()
            user   = FILETIME()
            ctypes.windll.kernel32.GetSystemTimes(
                ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
            )
            def ft2int(ft):
                return (ft.dwHighDateTime << 32) | ft.dwLowDateTime
            idle_t   = ft2int(idle)
            kernel_t = ft2int(kernel)
            user_t   = ft2int(user)
            total = kernel_t + user_t
            if self._prev_cpu_total is not None:
                d_idle  = idle_t   - self._prev_cpu_idle
                d_total = total    - self._prev_cpu_total
                if d_total > 0:
                    cpu_pct = max(0.0, min(100.0, (1.0 - d_idle / d_total) * 100))
                    self._prev_cpu_idle  = idle_t
                    self._prev_cpu_total = total
                    return round(cpu_pct, 1)
            self._prev_cpu_idle  = idle_t
            self._prev_cpu_total = total
            return 0.0
        except Exception:
            pass
        # Fallback PowerShell (goi 1 lan neu ctypes that bai)
        try:
            ok_, out, _ = ps(
                "(Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average",
                timeout=5
            )
            if ok_ and out.strip():
                return float(out.strip())
        except Exception:
            pass
        return 0.0

    # ── RAM % via ctypes GlobalMemoryStatusEx (non-blocking) ──────────────────
    def _get_ram_pct(self) -> float:
        """
        [PATCHED] Dung ctypes GlobalMemoryStatusEx thay vi wmic.
        Nhanh hon ~1000x, khong sinh tien trinh con, khong bi treo tren Win11.
        """
        try:
            import ctypes
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength",                ctypes.c_ulong),
                    ("dwMemoryLoad",            ctypes.c_ulong),
                    ("ullTotalPhys",            ctypes.c_ulonglong),
                    ("ullAvailPhys",            ctypes.c_ulonglong),
                    ("ullTotalPageFile",        ctypes.c_ulonglong),
                    ("ullAvailPageFile",        ctypes.c_ulonglong),
                    ("ullTotalVirtual",         ctypes.c_ulonglong),
                    ("ullAvailVirtual",         ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return float(stat.dwMemoryLoad)  # dwMemoryLoad la % RAM dang dung, san co
        except Exception:
            pass

    # ── Network bytes via GetIfEntry2 (ctypes, khong sinh tien trinh con) ────
    def _get_net_bytes(self):
        """
        [PATCHED] Dung ctypes GetIfTable thay netstat shell=True.
        Tong byte sent/recv tren tat ca interface.
        """
        try:
            import ctypes
            import ctypes.wintypes
            # GetIfTable2 khong can shell, lay truc tiep tu iphlpapi
            # Fallback nhe: doc tu netstat -e voi list args (shell=False)
            ok_, out, _ = run_cmd(["netstat", "-e"], shell=False, timeout=5)
            for line in (out or "").splitlines():
                parts = line.split()
                if len(parts) >= 3 and parts[0].lower() == "bytes":
                    return int(parts[1].replace(",","")), int(parts[2].replace(",",""))
        except Exception:
            pass
        return 0, 0

    def _poll(self):
        while self._running:
            cpu = self._get_cpu_pct()
            ram = self._get_ram_pct()
            sent, recv = self._get_net_bytes()
            d_sent = max(0, sent - self._prev_net_sent) / 1024  # KB/s
            d_recv = max(0, recv - self._prev_net_recv) / 1024
            self._prev_net_sent = sent
            self._prev_net_recv = recv
            with self._lock:
                self.cpu_history.append(cpu)
                self.ram_history.append(ram)
                self.net_sent.append(d_sent)
                self.net_recv.append(d_recv)
            time.sleep(1)

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread  = threading.Thread(target=self._poll, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "cpu":      list(self.cpu_history),
                "ram":      list(self.ram_history),
                "net_sent": list(self.net_sent),
                "net_recv": list(self.net_recv),
            }

_metrics = MetricsCollector()

# =============================================================================
#  PLUGIN SYSTEM  (v9)
# =============================================================================
PLUGIN_DIR = os.path.join(APP_DIR, "plugins")

def ensure_plugin_dir():
    os.makedirs(PLUGIN_DIR, exist_ok=True)
    readme = os.path.join(PLUGIN_DIR, "README.txt")
    if not os.path.exists(readme):
        with open(readme, "w", encoding="utf-8") as f:
            f.write(textwrap.dedent("""
            WinOptimizer v9 – Plugin Directory
            ====================================
            Dat file .py vao thu muc nay.
            Moi plugin phai dinh nghia:
              PLUGIN_NAME = "Ten Plugin"
              PLUGIN_DESC = "Mo ta ngan"
              def run(log_fn, ok_fn, warn_fn) -> dict:
                  # log_fn("..."), ok_fn("..."), warn_fn("...")
                  return {"freed": 0, "deleted": 0, "notes": ""}
            Plugin se xuat hien trong Tab Plugins va co the chay tu GUI/CLI.
            """).strip())

_loaded_plugins: list = []

def load_plugins() -> list:
    """Doc va load tat ca .py file trong thu muc plugins/."""
    global _loaded_plugins
    ensure_plugin_dir()
    plugins = []
    for fname in sorted(os.listdir(PLUGIN_DIR)):
        if not fname.endswith(".py"):
            continue
        path = os.path.join(PLUGIN_DIR, fname)
        try:
            import importlib.util
            spec   = importlib.util.spec_from_file_location(fname[:-3], path)
            mod    = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            plugins.append({
                "name":    getattr(mod, "PLUGIN_NAME", fname),
                "desc":    getattr(mod, "PLUGIN_DESC", ""),
                "run":     getattr(mod, "run", None),
                "module":  mod,
                "file":    fname,
            })
            info(f"Plugin loaded: {getattr(mod,'PLUGIN_NAME',fname)}")
        except Exception as exc:
            warn(f"Plugin load failed ({fname}): {exc}")
    _loaded_plugins = plugins
    return plugins

def run_plugin(plugin: dict) -> dict:
    if not callable(plugin.get("run")):
        warn(f"Plugin '{plugin['name']}' khong co ham run()")
        return {}
    try:
        result = plugin["run"](info, ok, warn)
        ok(f"Plugin '{plugin['name']}' hoan thanh: {result}")
        return result or {}
    except Exception as exc:
        err(f"Plugin '{plugin['name']}' loi: {exc}")
        return {}

# =============================================================================
#  CONTEXT MENU INTEGRATION  (v9 – dang ky "Clean Here" vao Explorer)
# =============================================================================
_CTX_KEY_DIR   = r"Directory\shell\WinOptimizerCleanHere"
_CTX_KEY_DRIVE = r"Drive\shell\WinOptimizerCleanHere"
_CTX_LABEL     = "WinOptimizer: Clean Here"

def _ctx_script_path() -> str:
    return os.path.abspath(sys.argv[0])

def register_context_menu():
    """Them 'Clean Here' vao menu chuot phai cua thu muc va o dia."""
    section("Context Menu Integration")
    py_exe = sys.executable
    script = _ctx_script_path()
    cmd    = f'"{py_exe}" "{script}" --clean-path "%V"'
    for base_key in [_CTX_KEY_DIR, _CTX_KEY_DRIVE]:
        reg_add("HKCR", base_key,           "",      _CTX_LABEL, REG_SZ)
        reg_add("HKCR", base_key,           "Icon",  py_exe,     REG_SZ)
        reg_add("HKCR", f"{base_key}\\command", "", cmd,         REG_SZ)
    ok(f"Context menu 'Clean Here' da duoc dang ky")
    info("Chuot phai vao thu muc hoac o dia se thay menu 'WinOptimizer: Clean Here'")

def unregister_context_menu():
    """Xoa 'Clean Here' khoi menu chuot phai."""
    section("Remove Context Menu")
    for base_key in [_CTX_KEY_DIR, _CTX_KEY_DRIVE]:
        reg_delete_key("HKCR", f"{base_key}\\command")
        reg_delete_key("HKCR", base_key)
    ok("Da xoa context menu 'Clean Here'")

def clean_path_mode(path: str):
    """Chay don dep tren thu muc cu the (duoc goi tu context menu)."""
    _setup_logging()
    ensure_dirs()
    section(f"Clean Path: {path}")
    r1 = CleanResult("TempClean")
    if os.path.isdir(path):
        f, d = _del_dir_contents(path)
        r1.add(f"Temp trong: {path}", f, d)
    run_cmd(["ipconfig", "/flushdns"], shell=False)
    ok(f"Clean Path xong: {fmt_bytes(r1.freed)} giai phong")
    _show_balloon("WinOptimizer", f"Clean xong {path}: {fmt_bytes(r1.freed)}")

# =============================================================================
#  UPDATE CHECKER  (v9)
# =============================================================================
UPDATE_CHECK_URL = "https://raw.githubusercontent.com/local/winoptimizer/main/version.json"

def check_for_updates(timeout_s: int = 8) -> dict:
    """
    Kiem tra phien ban moi bang cach doc file version.json tu URL.
    Neu khong ket duoc mang, tra ve {'available': False}.
    """
    section("Update Checker")
    result = {"available": False, "latest": APP_VERSION, "notes": ""}
    try:
        import urllib.request
        req = urllib.request.Request(
            UPDATE_CHECK_URL,
            headers={"User-Agent": f"WinOptimizer/{APP_VERSION}"}
        )
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        latest  = data.get("version", APP_VERSION)
        notes   = data.get("notes", "")
        avail   = latest != APP_VERSION
        result  = {"available": avail, "latest": latest, "notes": notes}
        if avail:
            ok(f"Co phien ban moi: v{latest}")
            if notes:
                info(f"Ghi chu: {notes}")
        else:
            ok(f"Ban dang dung phien ban moi nhat: v{APP_VERSION}")
    except Exception as exc:
        info(f"Khong kiem tra duoc update (co the do khong co mang): {exc}")
    return result

# =============================================================================
#  NOTIFICATION CENTER  (v9)
# =============================================================================
_NOTIF_FILE = os.path.join(APP_DIR, "notifications.json")
_MAX_NOTIFS  = 50

class NotificationCenter:
    """
    Quan ly danh sach thong bao trong app.
    Luu vao file JSON, doc lai khi khoi dong.
    """
    LEVELS = {"info": "ℹ", "ok": "✅", "warn": "⚠", "err": "❌"}

    def __init__(self):
        self._items: list = []
        self._lock = threading.RLock()
        self._seen_count = 0  # so notif da "doc"
        self._load()
        self._callbacks: list = []

    def _load(self):
        try:
            with open(_NOTIF_FILE, "r", encoding="utf-8") as f:
                self._items = json.load(f)[-_MAX_NOTIFS:]
        except Exception:
            self._items = []
        self._seen_count = len(self._items)

    def _save(self):
        # [PATCHED v9.1] Ghi nguyen tu + khoa de tranh hong file khi
        # nhieu luong (parallel cleaner) cung push 1 luc.
        with self._lock:
            try:
                os.makedirs(APP_DIR, exist_ok=True)
                tmp = _NOTIF_FILE + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self._items[-_MAX_NOTIFS:], f, ensure_ascii=False)
                os.replace(tmp, _NOTIF_FILE)
            except Exception:
                pass

    def push(self, msg: str, level: str = "info"):
        item = {
            "ts":    datetime.now().isoformat(timespec="seconds"),
            "level": level,
            "msg":   msg,
        }
        with self._lock:
            self._items.append(item)
            if len(self._items) > _MAX_NOTIFS:
                self._items = self._items[-_MAX_NOTIFS:]
            cbs = list(self._callbacks)
        self._save()
        for cb in cbs:
            try:
                cb(item)
            except Exception:
                pass

    def all(self) -> list:
        with self._lock:
            return list(reversed(self._items))

    def unread_count(self) -> int:
        # [PATCHED v9.1] "Chua doc" = so notif moi ke tu lan mark_read cuoi.
        with self._lock:
            return max(0, len(self._items) - self._seen_count)

    def mark_read(self):
        with self._lock:
            self._seen_count = len(self._items)

    def clear(self):
        with self._lock:
            self._items = []
            self._seen_count = 0
        self._save()

    def on_new(self, callback):
        self._callbacks.append(callback)

_notif = NotificationCenter()

# Override ok/warn/err to also push notifications for important events
_orig_ok   = ok
_orig_warn = warn
_orig_err  = err

def ok(msg):
    _orig_ok(msg)
    if any(kw in msg.lower() for kw in ["hoan tat","xong","da ap dung","da tao","da xoa","giai phong"]):
        _notif.push(msg, "ok")

def warn(msg):
    _orig_warn(msg)
    _notif.push(msg, "warn")

def err(msg):
    _orig_err(msg)
    _notif.push(msg, "err")

# =============================================================================
#  HOSTS FILE EDITOR  (v9)
# =============================================================================
HOSTS_PATH = os.path.join(WINDIR, r"System32\drivers\etc\hosts")

_AD_BLOCK_ENTRIES = [
    "0.0.0.0 ads.google.com",
    "0.0.0.0 pagead2.googlesyndication.com",
    "0.0.0.0 adservice.google.com",
    "0.0.0.0 doubleclick.net",
    "0.0.0.0 www.googletagservices.com",
    "0.0.0.0 telemetry.microsoft.com",
    "0.0.0.0 vortex.data.microsoft.com",
    "0.0.0.0 settings-win.data.microsoft.com",
    "0.0.0.0 watson.telemetry.microsoft.com",
    "0.0.0.0 sqm.microsoft.com",
    "0.0.0.0 oca.microsoft.com",
    "0.0.0.0 statsfe1.ws.microsoft.com",
    "0.0.0.0 statsfe2.ws.microsoft.com",
    "0.0.0.0 compatexchange.cloudapp.net",
    "0.0.0.0 cs1.wpc.v0cdn.net",
    "0.0.0.0 a-0001.a-msedge.net",
    "0.0.0.0 activity.windows.com",
    "0.0.0.0 bingads.microsoft.com",
]

def read_hosts() -> str:
    try:
        with open(HOSTS_PATH, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception as exc:
        warn(f"Khong doc duoc hosts file: {exc}")
        return ""

def write_hosts(content: str) -> bool:
    try:
        with open(HOSTS_PATH, "w", encoding="utf-8") as f:
            f.write(content)
        run_cmd(["ipconfig", "/flushdns"], shell=False)
        ok("Hosts file da duoc cap nhat, DNS flushed")
        return True
    except Exception as exc:
        err(f"Khong ghi duoc hosts file: {exc}")
        return False

def add_ad_block_to_hosts():
    """Them danh sach block quang cao/telemetry vao hosts file."""
    section("Hosts File – Block Ads & Telemetry")
    current = read_hosts()
    marker  = "# === WinOptimizer v9 Ad Block ==="
    if marker in current:
        info("Ad block entries da ton tai trong hosts file.")
        return
    backup_path = HOSTS_PATH + ".bak"
    try:
        shutil.copy2(HOSTS_PATH, backup_path)
        ok(f"Backup: {backup_path}")
    except Exception:
        pass
    new_block = "\n" + marker + "\n" + "\n".join(_AD_BLOCK_ENTRIES) + "\n# === End WinOptimizer ===\n"
    write_hosts(current + new_block)
    ok(f"Da them {len(_AD_BLOCK_ENTRIES)} entries vao hosts file")

def remove_ad_block_from_hosts():
    """Xoa block quang cao da them boi WinOptimizer khoi hosts file."""
    current = read_hosts()
    start_m = "# === WinOptimizer v9 Ad Block ==="
    end_m   = "# === End WinOptimizer ==="
    if start_m not in current:
        info("Khong tim thay WinOptimizer entries trong hosts file.")
        return
    import re as _re
    new_content = _re.sub(
        rf"\n{_re.escape(start_m)}.*?{_re.escape(end_m)}\n",
        "", current, flags=_re.DOTALL
    )
    write_hosts(new_content)
    ok("Da xoa WinOptimizer entries khoi hosts file")

# =============================================================================
#  STARTUP DELAY REDUCER  (v9)
# =============================================================================
def reduce_startup_delay():
    """
    Dat StartupDelayInMSec = 0 cho tat ca startup app de Windows khoi dong nhanh hon.
    Backup gia tri cu truoc khi sua.
    """
    section("Startup Delay Reducer")
    delay_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Serialize"
    backup_registry_values()
    ok_, _, _ = reg_add("HKCU", delay_path, "StartupDelayInMSec", 0, REG_DWORD)
    if ok_:
        ok("StartupDelayInMSec = 0 (startup apps khong bi delay sau boot)")
    else:
        warn("Khong set duoc StartupDelayInMSec")
    # Also disable startup delay service
    ok_, _, _ = reg_add(
        "HKLM",
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Serialize",
        "StartupDelayInMSec", 0, REG_DWORD
    )
    if ok_:
        ok("HKLM StartupDelayInMSec = 0")

# =============================================================================
#  POWER PLAN VIEWER  (v9 – hien thi tat ca power plan)
# =============================================================================
def list_all_power_plans() -> list:
    """Liet ke tat ca power plan voi GUID, ten, trang thai active."""
    return list_power_schemes()

def switch_power_plan(guid: str) -> bool:
    """Chuyen sang power plan theo GUID."""
    return set_active_power_scheme(guid)

def delete_custom_power_plan(guid: str) -> bool:
    """Xoa power plan tuy chinh (khong the xoa built-in plans)."""
    ok_, _, err_ = run_cmd(["powercfg", "/delete", str(guid)], shell=False)
    if ok_:
        ok(f"Da xoa power plan: {guid}")
    else:
        warn(f"Khong xoa duoc: {err_}")
    return ok_

# =============================================================================
#  WINDOWS SERVICES GUI DATA  (v9 – lay danh sach day du)
# =============================================================================
def get_all_services(filter_state: str = None) -> list:
    """
    Lay danh sach tat ca service.
    filter_state: 'running', 'stopped', None (tat ca).
    """
    ok_, out, _ = run_cmd(
        ["sc", "query", "type=", "all", "state=", "all"],
        shell=False, timeout=30
    )
    services = []
    current  = {}
    for line in (out or "").splitlines():
        line = line.strip()
        if line.startswith("SERVICE_NAME:"):
            if current.get("name"):
                services.append(current)
            current = {"name": line.split(":",1)[-1].strip()}
        elif line.startswith("DISPLAY_NAME:"):
            current["display"] = line.split(":",1)[-1].strip()
        elif "STATE" in line and ":" in line:
            parts = line.split()
            current["state"] = parts[-1].lower() if parts else ""
        elif line.startswith("TYPE"):
            pass
    if current.get("name"):
        services.append(current)

    if filter_state:
        services = [s for s in services if s.get("state","") == filter_state]
    return services

# =============================================================================
#  PARALLEL CLEANER  (v9 – chay modules song song bang ThreadPoolExecutor)
# =============================================================================
import concurrent.futures

def full_cleaner_parallel(s: dict = None) -> list:
    """
    Chay Full Cleaner song song (parallel threads).
    Nhanh hon 2-3x so voi chay tuan tu.
    """
    if s is None:
        s = load_settings()
    section("Full Cleaner Parallel – Don Dep Song Song")
    t0          = time.time()
    free_before = free_space_gb()

    modules = []
    if s.get("clean_temp",         True):  modules.append(("Temp",       cleanup_temp_files))
    if s.get("clean_browser",      True):  modules.append(("Browser",    cleanup_browser_cache))
    if s.get("clean_game",         True):  modules.append(("Game",       cleanup_game_cache))
    if s.get("clean_office",       True):  modules.append(("Office",     cleanup_office_and_apps))
    if s.get("clean_devtools",     True):  modules.append(("DevTools",   cleanup_dev_tools))
    if s.get("clean_system_files", True):  modules.append(("System",     cleanup_system_files))
    if s.get("clean_recycle",      True):  modules.append(("Recycle",    cleanup_recycle_and_thumbs))
    if s.get("clean_security",     False): modules.append(("Privacy",    cleanup_security_privacy))
    if IS_WIN10_PLUS:                      modules.append(("Store",      cleanup_store_cache))
    if s.get("clean_old_downloads",False): modules.append(("Downloads",  cleanup_old_downloads))

    results   = []
    n         = len(modules)
    completed = [0]

    def _run_module(label_fn_pair):
        label, fn = label_fn_pair
        try:
            r = fn()
            completed[0] += 1
            _set_progress(int(completed[0] * 100 / n), f"Done: {label}")
            return r
        except Exception as exc:
            err(f"{label} loi: {exc}")
            log(traceback.format_exc(), "error")
            return CleanResult(label)

    # Max 4 threads concurrently (I/O bound)
    max_workers = min(4, n)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_run_module, pair): pair[0] for pair in modules}
        for fut in concurrent.futures.as_completed(futures):
            r = fut.result()
            if r:
                results.append(r)

    if s.get("optimize_drives",  True):  optimize_drives()
    if s.get("optimize_network", True):  optimize_network()

    _set_progress(100, "Hoan thanh!")
    _end_progress()

    free_after = free_space_gb()
    gained     = round(free_after - free_before, 1)
    duration   = round(time.time() - t0, 1)
    ok(f"Full Cleaner Parallel xong trong {duration}s | +{gained}GB | {max_workers} threads")
    note(f"Parallel cleaner: +{gained}GB trong {duration}s")

    s["last_run"] = datetime.now().isoformat(timespec="seconds")
    save_settings(s)
    _notif.push(f"Full Cleaner: giai phong {gained}GB trong {duration}s", "ok")
    return results

# Override the original full_cleaner to use parallel version
full_cleaner = full_cleaner_parallel

# =============================================================================
#  HTML REPORT v4  (v9 – them Monitor snapshot, plugin kết quả)
# =============================================================================
def generate_html_report_v4(results: list, sysinfo: dict, duration_s: float,
                              profile_name: str = "",
                              bench_results: dict = None,
                              ba_entry: dict = None,
                              metrics_snapshot: dict = None,
                              plugin_results: list = None) -> str:
    """Bao cao HTML v4 voi them Monitor snapshot va plugin results."""
    # Build monitor section
    monitor_html = ""
    if metrics_snapshot:
        cpu_vals = metrics_snapshot.get("cpu", [])
        ram_vals = metrics_snapshot.get("ram", [])
        avg_cpu  = round(sum(cpu_vals)/len(cpu_vals), 1) if cpu_vals else 0
        avg_ram  = round(sum(ram_vals)/len(ram_vals), 1) if ram_vals else 0
        max_cpu  = max(cpu_vals) if cpu_vals else 0
        monitor_html = f"""
        <h2>System Monitor Snapshot</h2>
        <div class='grid3'>
          <div class='card'><div style='color:#8b949e'>Avg CPU</div>
            <div class='big'>{avg_cpu}%</div>
            <div style='color:#8b949e;font-size:.8em'>Peak: {max_cpu}%</div></div>
          <div class='card'><div style='color:#8b949e'>Avg RAM</div>
            <div class='big'>{avg_ram}%</div></div>
          <div class='card'><div style='color:#8b949e'>Samples</div>
            <div class='big'>{len(cpu_vals)}</div></div>
        </div>"""

    # Build plugin section
    plugin_html = ""
    if plugin_results:
        rows = "".join(
            f"<tr><td>{p.get('name','?')}</td>"
            f"<td>{fmt_bytes(p.get('freed',0))}</td>"
            f"<td>{p.get('notes','')}</td></tr>"
            for p in plugin_results
        )
        plugin_html = f"""
        <h2>Plugin Results</h2>
        <table><tr><th>Plugin</th><th>Freed</th><th>Notes</th></tr>{rows}</table>"""

    # Delegate to v3 for the rest, inject extra sections
    path = generate_html_report_v3(
        results, sysinfo, duration_s, profile_name, bench_results, ba_entry
    )
    # Append extra sections
    try:
        with open(path, "r", encoding="utf-8") as f:
            html = f.read()
        insert_before = "<footer"
        html = html.replace(insert_before, monitor_html + plugin_html + "\n" + insert_before)
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
    except Exception:
        pass
    ok(f"HTML Report v4: {path}")
    return path

# =============================================================================
#  GUI – tkinter  (NEW v5)
# =============================================================================
DARK_BG     = "#0d1117"
DARK_PANEL  = "#161b22"
DARK_BORDER = "#30363d"
ACCENT      = "#58a6ff"
ACCENT2     = "#a371f7"
GREEN       = "#3fb950"
YELLOW      = "#d29922"
RED         = "#f85149"
FG          = "#e6edf3"
FG_DIM      = "#8b949e"

TAG_COLORS = {
    "ok":   GREEN,
    "warn": YELLOW,
    "err":  RED,
    "info": ACCENT,
    "sect": ACCENT2,
}

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME}  {APP_SUBTITLE}")
        self.geometry("1080x720")
        self.minsize(860, 580)
        self.resizable(True, True)

        self.settings  = load_settings()
        self._theme    = self.settings.get("theme", "dark")
        self._T        = THEMES[self._theme]
        self._running  = False
        self._thread   = None
        self._tray_win = None
        self._alive    = True

        # Thread-safe UI update queue – MUST be created before _build_ui
        self._ui_queue = _queue.Queue()

        self.configure(bg=self._T["bg"])

        # Start background metrics collection
        _metrics.start()

        # Load plugins
        self._plugins = load_plugins()

        # Register GUI callbacks
        global _gui_log_cb, _gui_progress_cb
        _gui_log_cb      = self._append_log
        _gui_progress_cb = self._update_progress

        # Register notification callback
        _notif.on_new(self._on_notification)

        self._build_ui()
        self._bind_hotkeys()
        # Start queue pump for thread-safe UI updates
        self._pump_ui_queue()
        self._refresh_sysinfo()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Splash "What's new" on first launch of this version
        last_ver = self.settings.get("_last_seen_version", "")
        if last_ver != APP_VERSION:
            self.after(400, self._show_whats_new)
            self.settings["_last_seen_version"] = APP_VERSION
            save_settings(self.settings)

    # ── Build UI ─────────────────────────────────────────────────────────────
    def _build_ui(self):
        T = self._T
        banner = tk.Frame(self, bg=T["panel"], pady=6)
        banner.pack(fill="x")
        tk.Label(banner, text=f"  {APP_NAME}", font=("Segoe UI", 14, "bold"),
                 bg=T["panel"], fg=T["accent"]).pack(side="left")
        tk.Label(banner, text=APP_SUBTITLE, font=("Segoe UI", 9),
                 bg=T["panel"], fg=T["fg_dim"]).pack(side="left", padx=6)

        # Theme toggle button (top-right)
        self._theme_btn_text = tk.StringVar(
            value="☀ Light" if self._theme == "dark" else "🌙 Dark"
        )
        tk.Button(banner, textvariable=self._theme_btn_text,
                  command=self._toggle_theme,
                  bg=T["border"], fg=T["fg"], activebackground=T["panel"],
                  font=("Segoe UI", 8), relief="flat", cursor="hand2",
                  padx=8, pady=3).pack(side="right", padx=8)

        # OS badge
        os_badge = get_os_friendly_name()
        tk.Label(banner, text=f"  {os_badge}", font=("Segoe UI", 8),
                 bg=T["panel"], fg=T["accent2"]).pack(side="right", padx=4)

        # ── Main body ───────────────────────────────────────────────────────
        body = tk.Frame(self, bg=T["bg"])
        body.pack(fill="both", expand=True, padx=10, pady=(6, 4))

        left = tk.Frame(body, bg=T["bg"], width=520)
        left.pack(side="left", fill="both", expand=True)
        left.pack_propagate(False)

        nb = ttk.Notebook(left)
        nb.pack(fill="both", expand=True)
        self._nb = nb
        # [PATCHED v2] Bat/tat Monitor loop khi nguoi dung doi tab
        # Tranh vong lap ve do thi chay ngam khi khong ai nhin thay tab Monitor
        self._nb.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TNotebook",     background=T["bg"],    borderwidth=0)
        style.configure("TNotebook.Tab", background=T["panel"], foreground=T["fg_dim"],
                         padding=[9, 4], font=("Segoe UI", 9))
        style.map("TNotebook.Tab",       background=[("selected", T["border"])],
                                          foreground=[("selected", T["accent"])])
        style.configure("TCheckbutton",  background=T["panel"], foreground=T["fg"],
                         font=("Segoe UI", 9))
        style.map("TCheckbutton",        background=[("active", T["panel"])])
        style.configure("Horizontal.TProgressbar",
                         troughcolor=T["border"], background=T["accent"], thickness=14)
        style.configure("TCombobox", fieldbackground=T["entry_bg"],
                         background=T["border"], foreground=T["fg"])

        self._build_tab_optimize(nb)
        self._build_tab_cleaner(nb)
        self._build_tab_monitor(nb)
        self._build_tab_tools(nb)
        self._build_tab_tweaks(nb)
        self._build_tab_benchmark(nb)
        self._build_tab_services(nb)
        self._build_tab_hosts(nb)
        self._build_tab_plugins(nb)
        self._build_tab_processes(nb)
        self._build_tab_network(nb)
        self._build_tab_history(nb)
        self._build_tab_startup(nb)
        self._build_tab_schedule(nb)
        self._build_tab_settings(nb)
        self._build_tab_sysinfo(nb)

        # Right panel: log
        right = tk.Frame(body, bg=T["bg"], width=440)
        right.pack(side="right", fill="both", expand=True, padx=(8, 0))
        right.pack_propagate(False)

        hdr = tk.Frame(right, bg=T["bg"])
        hdr.pack(fill="x")
        tk.Label(hdr, text="Activity Log", font=("Segoe UI", 10, "bold"),
                 bg=T["bg"], fg=T["fg_dim"]).pack(side="left")
        tk.Label(hdr, text="  Ctrl+C = Clear  |  Ctrl+R = Refresh",
                 font=("Segoe UI", 7), bg=T["bg"], fg=T["fg_dim"]).pack(side="left")

        self.log_box = scrolledtext.ScrolledText(
            right, bg=T["log_bg"], fg=T["fg"], font=("Consolas", 8),
            state="disabled", wrap="word", insertbackground=T["fg"],
            bd=0, highlightthickness=1, highlightbackground=T["border"]
        )
        self.log_box.pack(fill="both", expand=True, pady=(4, 0))
        for tag, col in {
            "ok": T["green"], "warn": T["yellow"], "err": T["red"],
            "info": T["accent"], "sect": T["accent2"],
        }.items():
            self.log_box.tag_configure(tag, foreground=col)

        # Before/After panel
        self._ba_frame = tk.Frame(right, bg=T["border"], pady=2)
        self._ba_frame.pack(fill="x", pady=(4, 0))
        self._ba_label = tk.StringVar(value="  Chua co du lieu before/after")
        tk.Label(self._ba_frame, textvariable=self._ba_label,
                 bg=T["border"], fg=T["fg_dim"], font=("Segoe UI", 8),
                 anchor="w").pack(fill="x", padx=6)

        # Progress bar
        prog_row = tk.Frame(right, bg=T["bg"], pady=4)
        prog_row.pack(fill="x")
        self.progress_var   = tk.IntVar(value=0)
        self.progress_label = tk.StringVar(value="")
        ttk.Progressbar(prog_row, variable=self.progress_var, maximum=100,
                         style="Horizontal.TProgressbar").pack(fill="x")
        tk.Label(prog_row, textvariable=self.progress_label,
                 bg=T["bg"], fg=T["fg_dim"], font=("Segoe UI", 8)).pack(anchor="w")

        # Bottom buttons
        btn_row = tk.Frame(right, bg=T["bg"])
        btn_row.pack(fill="x", pady=(2, 0))
        self._btn("Clear Log",     btn_row, self._clear_log,           color=T["fg_dim"]).pack(side="right")
        self._btn("Open Log Dir",  btn_row, lambda: os.startfile(LOG_DIR)).pack(side="right", padx=4)
        self._btn("Open Report",   btn_row, self._open_latest_report).pack(side="right", padx=4)
        self._btn("⬇ Tray",        btn_row, self._minimize_to_tray,    color=T["accent2"]).pack(side="left")

    # ── Tab: Optimization Profiles ──────────────────────────────────────────
    def _build_tab_optimize(self, nb):
        T = self._T
        tab = self._tab(nb, t("tab_optimize"))
        profiles = [
            ("🟢 Auto Tune",            auto_tune,          "Tu dong phat hien may ban / laptop"),
            ("🎮 Gaming Plus",           gaming_plus_profile,"Game Mode ON, HAGS, power boost"),
            ("🔥 Competitive Extreme",   competitive_profile,"Do tre thap nhat, tat service thua"),
            ("🖥 Desktop Max",           desktop_max_profile,"Manh nhat, chi cho may ban"),
            ("💻 Laptop Turbo",          laptop_profile,     "Cam sac AC nhanh, pin tiet kiem"),
            ("📅 Everyday Safe",         safe_everyday_profile,"On dinh, nhanh hon mac dinh"),
        ]
        tk.Label(tab, text="Chon optimization profile:", font=("Segoe UI",10,"bold"),
                 bg=T["panel"], fg=T["fg"]).pack(anchor="w", padx=10, pady=(10,4))
        for label, fn, desc in profiles:
            row = tk.Frame(tab, bg=T["panel"])
            row.pack(fill="x", padx=10, pady=3)
            self._btn(label, row, lambda f=fn: self._run(f), w=22).pack(side="left")
            tk.Label(row, text=desc, bg=T["panel"], fg=T["fg_dim"],
                     font=("Segoe UI",8)).pack(side="left", padx=8)

        tk.Frame(tab, bg=T["border"], height=1).pack(fill="x", padx=10, pady=10)

        extras = [
            ("Registry Gaming Tweaks",  optimize_gaming_registry),
            ("Visual Effects OFF",      optimize_visuals),
            ("Mouse Precision OFF",     optimize_mouse),
            ("Low-Latency Registry",    optimize_low_latency_registry),
            ("Network Registry Tweaks", optimize_network_registry),
            ("⭐ Extra Tweaks v6",       optimize_extra_tweaks),
            ("HAGS Toggle",             enable_hags),
            ("Service Trim (Basic)",    lambda: apply_service_trim(False)),
            ("Service Trim (Extreme)",  lambda: apply_service_trim(True)),
            ("Task Trim",               apply_task_trim),
        ]
        tk.Label(tab, text="Tweaks don le:", font=("Segoe UI",9,"bold"),
                 bg=T["panel"], fg=T["fg_dim"]).pack(anchor="w", padx=10)
        cols = tk.Frame(tab, bg=T["panel"])
        cols.pack(fill="x", padx=10, pady=4)
        for i, (label, fn) in enumerate(extras):
            r, c = divmod(i, 2)
            self._btn(label, cols, lambda f=fn: self._run(f), w=24).grid(row=r, column=c, padx=4, pady=2, sticky="w")

        tk.Frame(tab, bg=T["border"], height=1).pack(fill="x", padx=10, pady=8)
        restore_row = tk.Frame(tab, bg=T["panel"])
        restore_row.pack(fill="x", padx=10)
        self._btn("↩ Restore All", restore_row, lambda: self._run(restore_all), color=T["yellow"], w=18).pack(side="left")
        self._btn("📌 Restore Point", restore_row, lambda: self._run(create_restore_point), w=18).pack(side="left", padx=6)

    # ── Tab: Cleaner ─────────────────────────────────────────────────────────
    def _build_tab_cleaner(self, nb):
        T = self._T
        tab = self._tab(nb, t("tab_cleaner"))
        tk.Label(tab, text="Don dep toan dien:", font=("Segoe UI",10,"bold"),
                 bg=T["panel"], fg=T["fg"]).pack(anchor="w", padx=10, pady=(10,4))
        self._btn("▶ Full Cleaner (Tat Ca)", tab,
                  lambda: self._run_and_report(full_cleaner), color=T["green"]).pack(padx=10, pady=4, anchor="w")
        tk.Frame(tab, bg=T["border"], height=1).pack(fill="x", padx=10, pady=6)
        tk.Label(tab, text="Tung module:", font=("Segoe UI",9,"bold"),
                 bg=T["panel"], fg=T["fg_dim"]).pack(anchor="w", padx=10)
        modules = [
            ("Temp & Prefetch",       cleanup_temp_files),
            ("Browser Cache",         cleanup_browser_cache),
            ("Game Launcher Cache",   cleanup_game_cache),
            ("Office & App Cache",    cleanup_office_and_apps),
            ("Dev Tools Cache",       cleanup_dev_tools),
            ("System Files",          cleanup_system_files),
            ("Recycle Bin & Thumbs",  cleanup_recycle_and_thumbs),
            ("Security & Privacy",    cleanup_security_privacy),
            ("Old Downloads (30d)",   cleanup_old_downloads),
            ("Network Optimize",      optimize_network),
            ("Drive Optimize",        optimize_drives),
        ]
        if IS_WIN10_PLUS:
            modules.append(("Windows Store Cache", cleanup_store_cache))
        cols = tk.Frame(tab, bg=T["panel"])
        cols.pack(fill="x", padx=10, pady=4)
        for i, (label, fn) in enumerate(modules):
            r, c = divmod(i, 2)
            self._btn(label, cols, lambda f=fn: self._run(f), w=24).grid(row=r, column=c, padx=4, pady=2, sticky="w")
        tk.Frame(tab, bg=T["border"], height=1).pack(fill="x", padx=10, pady=8)
        health_row = tk.Frame(tab, bg=T["panel"])
        health_row.pack(fill="x", padx=10)
        self._btn("SFC /scannow",    health_row, lambda: self._run(run_sfc),           w=18).pack(side="left")
        self._btn("DISM RestoreHealth", health_row, lambda: self._run(run_dism_restore), w=20).pack(side="left", padx=6)
        self._btn("Component Cleanup",  health_row, lambda: self._run(run_component_cleanup), w=20).pack(side="left", padx=6)

    # ── Tab: Tools (v6) ───────────────────────────────────────────────────────
    def _build_tab_tools(self, nb):
        T   = self._T
        T   = self._T
        tab = self._tab(nb, t("tab_tools"))

        # ── RAM Cleaner ──────────────────────────────────────────────────────
        ram_frame = tk.LabelFrame(tab, text=" RAM Cleaner ", bg=T["panel"],
                                   fg=T["accent"], font=("Segoe UI",9,"bold"), bd=1)
        ram_frame.pack(fill="x", padx=10, pady=(10,4))
        self.ram_label = tk.StringVar(value="RAM: --")
        tk.Label(ram_frame, textvariable=self.ram_label, bg=T["panel"],
                 fg=T["fg"], font=("Consolas",9)).pack(side="left", padx=8, pady=6)
        self._btn("Refresh RAM", ram_frame, self._refresh_ram_info).pack(side="left", padx=4)
        self._btn("🧠 Clean RAM", ram_frame, lambda: self._run(self._do_ram_clean),
                   color=T["green"]).pack(side="left", padx=4)

        # ── Disk Analyzer ────────────────────────────────────────────────────
        disk_frame = tk.LabelFrame(tab, text=" Disk Analyzer ", bg=T["panel"],
                                    fg=T["accent"], font=("Segoe UI",9,"bold"), bd=1)
        disk_frame.pack(fill="both", expand=True, padx=10, pady=4)

        ctrl_row = tk.Frame(disk_frame, bg=T["panel"])
        ctrl_row.pack(fill="x", padx=6, pady=(6,2))
        tk.Label(ctrl_row, text="Quet thu muc:", bg=T["panel"], fg=T["fg"],
                 font=("Segoe UI",9)).pack(side="left")
        self.analyzer_path_var = tk.StringVar(value=SYSDRIVE + "\\")
        tk.Entry(ctrl_row, textvariable=self.analyzer_path_var, width=20,
                 bg=T["log_bg"], fg=T["fg"], insertbackground=T["fg"],
                 font=("Segoe UI",9)).pack(side="left", padx=4)
        self._btn("Browse", ctrl_row, self._browse_analyzer_path, w=8).pack(side="left")
        self._btn("🔍 Analyze", ctrl_row,
                   lambda: self._run(self._do_analyze), color=T["accent"]).pack(side="left", padx=4)

        # Disk usage bars
        self.disk_bar_frame = tk.Frame(disk_frame, bg=T["panel"])
        self.disk_bar_frame.pack(fill="x", padx=6, pady=(0,4))
        self._refresh_disk_bars()

        # Result list
        res_frame = tk.Frame(disk_frame, bg=T["panel"])
        res_frame.pack(fill="both", expand=True, padx=6, pady=(0,4))
        sb2 = tk.Scrollbar(res_frame, bg=T["panel"], troughcolor=T["bg"])
        self.analyzer_list = tk.Listbox(
            res_frame, yscrollcommand=sb2.set,
            bg=T["log_bg"], fg=T["fg"], font=("Consolas",8), bd=0,
            highlightthickness=1, highlightbackground=T["border"],
            selectbackground=T["accent"], selectforeground=T["bg"], height=8
        )
        sb2.config(command=self.analyzer_list.yview)
        self.analyzer_list.pack(side="left", fill="both", expand=True)
        sb2.pack(side="right", fill="y")

        # ── Hibernation + Pagefile ───────────────────────────────────────────
        misc_frame = tk.LabelFrame(tab, text=" Hibernation & Pagefile ", bg=T["panel"],
                                    fg=T["accent"], font=("Segoe UI",9,"bold"), bd=1)
        misc_frame.pack(fill="x", padx=10, pady=(4,6))
        self.hibern_var = tk.StringVar(value="Hibernate: --")
        tk.Label(misc_frame, textvariable=self.hibern_var, bg=T["panel"],
                 fg=T["fg"], font=("Consolas",9)).pack(side="left", padx=8, pady=4)
        self._btn("OFF Hibernate", misc_frame, lambda: self._run(lambda: toggle_hibernation(False)),
                   color=T["yellow"]).pack(side="left", padx=2)
        self._btn("ON Hibernate",  misc_frame, lambda: self._run(lambda: toggle_hibernation(True)),
                   color=T["green"]).pack(side="left", padx=2)

        pf_choices = ["auto","smart","gaming"]
        tk.Label(misc_frame, text="Pagefile:", bg=T["panel"], fg=T["fg"],
                 font=("Segoe UI",9)).pack(side="left", padx=(12,2))
        self.pf_mode_var = tk.StringVar(value="smart")
        ttk.Combobox(misc_frame, textvariable=self.pf_mode_var, values=pf_choices,
                     width=7, state="readonly").pack(side="left")
        self._btn("Apply", misc_frame,
                   lambda: self._run(lambda: optimize_pagefile(self.pf_mode_var.get())),
                   w=8).pack(side="left", padx=4)

        # ── Font Cache + Event Log ───────────────────────────────────────────
        misc2 = tk.Frame(tab, bg=T["panel"])
        misc2.pack(fill="x", padx=10, pady=(0,6))
        self._btn("🔤 Rebuild Font Cache",    misc2,
                   lambda: self._run(rebuild_font_cache), w=22).pack(side="left", padx=4)
        self._btn("📋 Clean Event Logs",       misc2,
                   lambda: self._run(cleanup_event_logs), color=T["yellow"], w=22).pack(side="left", padx=4)
        self._btn("💾 SSD TRIM",               misc2,
                   lambda: self._run(run_ssd_trim), color=T["accent2"], w=14).pack(side="left", padx=4)

        self._refresh_ram_info()
        self._refresh_hibern_info()

    def _refresh_ram_info(self):
        def _do():
            r = get_ram_usage()
            text = f"RAM: {r['used']}GB / {r['total']}GB ({r['pct']}% dang dung) | Con: {r['free']}GB"
            self._safe_after(lambda: self.ram_label.set(text))
        threading.Thread(target=_do, daemon=True).start()

    def _do_ram_clean(self):
        result = cleanup_ram()
        self._refresh_ram_info()
        freed = result.get("freed", 0)
        if freed > 0.05:
            _show_balloon("RAM Cleanup", f"Da giai phong ~{freed:.2f}GB RAM!")

    def _refresh_hibern_info(self):
        def _do():
            hf = get_hiberfil_size_gb()
            state = "ON" if get_hibernation_state() else "OFF"
            text = f"Hibernate: {state}  |  hiberfil.sys: {hf}GB"
            self._safe_after(lambda: self.hibern_var.set(text))
        threading.Thread(target=_do, daemon=True).start()

    def _refresh_disk_bars(self):
        T = self._T
        for w in self.disk_bar_frame.winfo_children():
            w.destroy()
        drives = detect_fixed_drives()
        for drive in drives[:4]:
            path = f"{drive}:\\"
            try:
                total, used, free = shutil.disk_usage(path)
                used_gb  = round(used  / (1 << 30), 1)
                total_gb = round(total / (1 << 30), 1)
                pct      = int(used * 100 / total) if total else 0
            except Exception:
                continue
            row = tk.Frame(self.disk_bar_frame, bg=T["panel"])
            row.pack(fill="x", pady=1)
            tk.Label(row, text=f"{drive}:", width=3, bg=T["panel"], fg=T["accent"],
                     font=("Consolas",9)).pack(side="left")
            canvas = tk.Canvas(row, height=14, bg=T["log_bg"], bd=0,
                                highlightthickness=0, width=200)
            canvas.pack(side="left", padx=4)
            canvas.update_idletasks()
            w_total = 200
            w_used  = int(w_total * pct / 100)
            color   = GREEN if pct < 70 else (YELLOW if pct < 90 else RED)
            canvas.create_rectangle(0, 0, w_total, 14, fill=T["border"], outline="")
            canvas.create_rectangle(0, 0, w_used,  14, fill=color,       outline="")
            tk.Label(row, text=f"{used_gb}/{total_gb}GB ({pct}%)",
                     bg=T["panel"], fg=T["fg_dim"], font=("Segoe UI",8)).pack(side="left")

    def _browse_analyzer_path(self):
        path = filedialog.askdirectory(initialdir=SYSDRIVE + "\\")
        if path:
            self.analyzer_path_var.set(path)

    def _do_analyze(self):
        path = self.analyzer_path_var.get().strip() or (SYSDRIVE + "\\")

        def _worker():
            results = analyze_disk_space(path, top_n=15, max_depth=3)
            self._safe_after(lambda: self._populate_analyzer_list(results))

        threading.Thread(target=_worker, daemon=True).start()

    def _populate_analyzer_list(self, results: list):
        T = self._T
        self.analyzer_list.delete(0, "end")
        if not results:
            self.analyzer_list.insert("end", "  (Khong co du lieu)")
            return
        max_sz = results[0][1] if results else 1
        for i, (path, sz) in enumerate(results, 1):
            pct = int(sz * 100 / max_sz) if max_sz else 0
            bar = "█" * (pct // 5)
            name = os.path.basename(path) or path
            line = f"  {i:2d}. {fmt_bytes(sz):>10}  {bar:<20}  {name}"
            self.analyzer_list.insert("end", line)
            if pct >= 80:
                self.analyzer_list.itemconfig(i - 1, fg=RED)
            elif pct >= 50:
                self.analyzer_list.itemconfig(i - 1, fg=YELLOW)

    # ── Tab: Tweaks (v8) – individual registry tweak checkboxes ──────────────
    def _build_tab_tweaks(self, nb):
        T   = self._T
        T   = self._T
        tab = self._tab(nb, t("tab_tweaks"))
        tk.Label(tab, text="Bat/tat tung tweak rieng le (tu dong doc trang thai hien tai)",
                 font=("Segoe UI", 9), bg=T["panel"], fg=T["fg_dim"]).pack(
                 anchor="w", padx=10, pady=(8, 4))

        canvas  = tk.Canvas(tab, bg=T["panel"], bd=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(tab, orient="vertical", command=canvas.yview)
        inner   = tk.Frame(canvas, bg=T["panel"])
        inner.bind("<Configure>", lambda e: canvas.configure(
            scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True, padx=(10, 0))
        scrollbar.pack(side="right", fill="y")

        self._tweak_vars = {}
        win_ver = 11 if IS_WIN11 else (10 if IS_WIN10_PLUS else 7)

        for item in ALL_TWEAKS:
            key, label, *_, win_min = item
            if win_min > win_ver:
                continue  # skip incompatible tweaks

            state = get_tweak_current_state(key)
            var   = tk.BooleanVar(value=bool(state) if state is not None else False)
            self._tweak_vars[key] = var

            row = tk.Frame(inner, bg=T["panel"])
            row.pack(fill="x", pady=1, padx=4)

            cb = ttk.Checkbutton(
                row, text=label, variable=var,
                command=lambda k=key, v=var: self._apply_single_tweak(k, v.get())
            )
            cb.pack(side="left")

            # State indicator
            col  = T["green"] if state is True else (T["fg_dim"] if state is None else T["yellow"])
            text = "● ON" if state is True else ("○ OFF" if state is False else "? N/A")
            tk.Label(row, text=text, bg=T["panel"], fg=col,
                     font=("Consolas", 8)).pack(side="left", padx=8)

        btn_row = tk.Frame(tab, bg=T["panel"])
        btn_row.pack(fill="x", padx=10, pady=6)
        self._btn("✅ Apply All ON",   btn_row,
                   lambda: self._run(self._apply_all_tweaks_on),  color=T["green"], w=16).pack(side="left")
        self._btn("🔄 Refresh States", btn_row,
                   lambda: self._run(lambda: self._safe_after(lambda: self._build_tab_tweaks_refresh())),
                   w=16).pack(side="left", padx=6)
        self._btn("↩ Restore All",    btn_row,
                   lambda: self._run(restore_registry_values), color=T["yellow"], w=14).pack(side="left")

    def _apply_single_tweak(self, key: str, enable: bool):
        backup_registry_values()
        apply_tweak(key, enable)

    def _apply_all_tweaks_on(self):
        backup_registry_values()
        done = 0
        for key, var in self._tweak_vars.items():
            if apply_tweak(key, True):
                var.set(True)
                done += 1
        ok(f"Applied {done} tweaks")

    def _build_tab_tweaks_refresh(self):
        # Rebuild the tweaks tab to refresh current states
        idx = None
        for i in range(self._nb.index("end")):
            if "Tweaks" in self._nb.tab(i, "text") or "🎛" in self._nb.tab(i, "text"):
                idx = i
                break
        if idx is not None:
            tab_widget = self._nb.nametowidget(self._nb.tabs()[idx])
            for w in tab_widget.winfo_children():
                w.destroy()
            # Rebuild
            T = self._T
            tk.Label(tab_widget, text="Bat/tat tung tweak rieng le:",
                     font=("Segoe UI", 9), bg=T["panel"], fg=T["fg_dim"]).pack(
                     anchor="w", padx=10, pady=(8, 4))
            ok("Tweaks tab refreshed – khoi dong lai app de xem day du.")

    # ── Tab: Benchmark (v8) ───────────────────────────────────────────────────
    def _build_tab_benchmark(self, nb):
        T   = self._T
        T   = self._T
        tab = self._tab(nb, t("tab_benchmark"))
        tk.Label(tab, text="Do toc do phan cung (CPU / RAM / Disk) – khong can cai them phan mem",
                 font=("Segoe UI", 9), bg=T["panel"], fg=T["fg_dim"]).pack(
                 anchor="w", padx=10, pady=(8, 4))

        # Controls
        ctrl = tk.Frame(tab, bg=T["panel"])
        ctrl.pack(fill="x", padx=10, pady=4)

        tk.Label(ctrl, text="RAM test (MB):", bg=T["panel"], fg=T["fg"],
                 font=("Segoe UI", 9)).pack(side="left")
        self.bench_ram_var = tk.StringVar(value="128")
        tk.Entry(ctrl, textvariable=self.bench_ram_var, width=6,
                 bg=T["entry_bg"], fg=T["fg"], insertbackground=T["fg"],
                 font=("Segoe UI", 9)).pack(side="left", padx=4)

        tk.Label(ctrl, text="Disk test (MB):", bg=T["panel"], fg=T["fg"],
                 font=("Segoe UI", 9)).pack(side="left", padx=(10, 0))
        self.bench_disk_var = tk.StringVar(value="64")
        tk.Entry(ctrl, textvariable=self.bench_disk_var, width=6,
                 bg=T["entry_bg"], fg=T["fg"], insertbackground=T["fg"],
                 font=("Segoe UI", 9)).pack(side="left", padx=4)

        self._btn("▶ Run Full Benchmark", ctrl,
                   lambda: self._run(self._do_full_benchmark),
                   color=T["green"], w=20).pack(side="left", padx=8)

        # Individual buttons
        ind = tk.Frame(tab, bg=T["panel"])
        ind.pack(fill="x", padx=10, pady=2)
        for label, fn in [
            ("CPU Only",    lambda: self._run(benchmark_cpu)),
            ("RAM Only",    lambda: self._run(lambda: benchmark_ram(int(self.bench_ram_var.get() or "64")))),
            ("Disk Only",   lambda: self._run(lambda: benchmark_disk(size_mb=int(self.bench_disk_var.get() or "64")))),
            ("Startup Time",lambda: self._run(self._do_startup_time)),
        ]:
            self._btn(label, ind, fn, w=14).pack(side="left", padx=3)

        tk.Frame(tab, bg=T["border"], height=1).pack(fill="x", padx=10, pady=8)

        # Results display
        tk.Label(tab, text="Ket qua:", font=("Segoe UI", 9, "bold"),
                 bg=T["panel"], fg=T["fg"]).pack(anchor="w", padx=10)

        res_frame = tk.Frame(tab, bg=T["panel"])
        res_frame.pack(fill="both", expand=True, padx=10, pady=4)

        # Score cards
        self.bench_cpu_var  = tk.StringVar(value="CPU:   --")
        self.bench_ram_res  = tk.StringVar(value="RAM:   --")
        self.bench_disk_res = tk.StringVar(value="Disk:  --")
        self.bench_boot_var = tk.StringVar(value="Boot:  --")

        for var, icon in [
            (self.bench_cpu_var,  "🔢"),
            (self.bench_ram_res,  "🧠"),
            (self.bench_disk_res, "💿"),
            (self.bench_boot_var, "⏱"),
        ]:
            row = tk.Frame(res_frame, bg=T["log_bg"], pady=6, padx=10,
                            highlightthickness=1, highlightbackground=T["border"])
            row.pack(fill="x", pady=3)
            tk.Label(row, text=icon, bg=T["log_bg"], font=("Segoe UI", 14)).pack(side="left")
            tk.Label(row, textvariable=var, bg=T["log_bg"], fg=T["fg"],
                     font=("Consolas", 10)).pack(side="left", padx=10)

        # Compare with previous
        self.bench_compare_var = tk.StringVar(value="")
        tk.Label(tab, textvariable=self.bench_compare_var,
                 bg=T["panel"], fg=T["fg_dim"], font=("Segoe UI", 8),
                 wraplength=460, justify="left").pack(anchor="w", padx=10, pady=4)

        self._last_bench = None

    def _do_full_benchmark(self):
        try:
            ram_mb  = int(self.bench_ram_var.get() or "128")
            disk_mb = int(self.bench_disk_var.get() or "64")
        except ValueError:
            ram_mb, disk_mb = 128, 64

        results = run_full_benchmark(ram_mb, disk_mb)
        cpu  = results.get("cpu",  {})
        ram  = results.get("ram",  {})
        disk = results.get("disk", {})

        self.bench_cpu_var.set(f"CPU:   {cpu.get('k_per_sec','?')}K SHA-256/s  ({cpu.get('duration','?')}s test)")
        self.bench_ram_res.set(f"RAM:   Read {ram.get('read_mbps','?')} MB/s  |  Write {ram.get('write_mbps','?')} MB/s")

        disk_lines = "  ".join(
            f"{drv}: R={d.get('read_mbps','?')} W={d.get('write_mbps','?')} MB/s"
            for drv, d in disk.items()
        )
        self.bench_disk_res.set(f"Disk:  {disk_lines}")

        # Compare with last run
        if self._last_bench:
            prev_cpu = self._last_bench.get("cpu", {}).get("k_per_sec", 0) or 0
            curr_cpu = cpu.get("k_per_sec", 0) or 0
            if prev_cpu:
                delta = round((curr_cpu - prev_cpu) / prev_cpu * 100, 1)
                arrow = "▲" if delta > 0 else "▼"
                self.bench_compare_var.set(
                    f"vs lan truoc: CPU {arrow}{abs(delta)}% | "
                    f"Prev: {prev_cpu}K/s | Now: {curr_cpu}K/s"
                )
        self._last_bench = results

        # Save to settings for persistence
        s = load_settings()
        s["_last_benchmark"] = {
            "ts":         datetime.now().isoformat(timespec="seconds"),
            "cpu_k_per_s": cpu.get("k_per_sec"),
            "ram_read":    ram.get("read_mbps"),
            "disk":       {drv: d.get("read_mbps") for drv, d in disk.items()},
        }
        save_settings(s)

    def _do_startup_time(self):
        data = get_startup_boot_time()
        last = data.get("last_boot_ms")
        avg  = data.get("avg_boot_ms")
        n    = data.get("samples", 0)
        if last:
            text = (f"Boot:  Last {last/1000:.1f}s  |  "
                    f"Avg {avg/1000:.1f}s  |  {n} mau")
        else:
            text = "Boot:  Khong doc duoc (EventLog co the bi tat)"
        self.bench_boot_var.set(text)
        ok(text.replace("Boot:  ", ""))

    # ── Tab: History (v8) – Before/After history ──────────────────────────────
    def _build_tab_history(self, nb):
        T   = self._T
        T   = self._T
        tab = self._tab(nb, t("tab_history"))
        tk.Label(tab, text="Lich su don dep truoc/sau moi phien lam viec",
                 font=("Segoe UI", 9), bg=T["panel"], fg=T["fg_dim"]).pack(
                 anchor="w", padx=10, pady=(8, 4))

        # History list
        list_frame = tk.Frame(tab, bg=T["panel"])
        list_frame.pack(fill="both", expand=True, padx=10, pady=4)

        sb = tk.Scrollbar(list_frame, bg=T["panel"], troughcolor=T["bg"])
        self.history_list = tk.Listbox(
            list_frame, yscrollcommand=sb.set, bg=T["log_bg"], fg=T["fg"],
            font=("Consolas", 8), bd=0, selectbackground=T["accent"],
            selectforeground=T["bg"], highlightthickness=1,
            highlightbackground=T["border"], height=12
        )
        sb.config(command=self.history_list.yview)
        self.history_list.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        # Mini chart canvas
        self.history_canvas = tk.Canvas(tab, bg=T["log_bg"], height=80, bd=0,
                                         highlightthickness=1,
                                         highlightbackground=T["border"])
        self.history_canvas.pack(fill="x", padx=10, pady=(0, 4))

        # Session total
        self.hist_session_var = tk.StringVar(value="")
        tk.Label(tab, textvariable=self.hist_session_var, bg=T["panel"],
                 fg=T["accent"], font=("Segoe UI", 9)).pack(anchor="w", padx=10)

        btn_row = tk.Frame(tab, bg=T["panel"])
        btn_row.pack(fill="x", padx=10, pady=4)
        self._btn("🔄 Refresh",      btn_row, self._refresh_history, w=12).pack(side="left")
        self._btn("🗑 Clear History", btn_row, self._clear_ba_history,
                   color=T["red"], w=14).pack(side="left", padx=6)

        # Also show duplicate finder + empty folder buttons here
        tk.Frame(tab, bg=T["border"], height=1).pack(fill="x", padx=10, pady=6)
        tk.Label(tab, text="Cong cu phan tich:", font=("Segoe UI", 9, "bold"),
                 bg=T["panel"], fg=T["fg_dim"]).pack(anchor="w", padx=10)
        extra_row = tk.Frame(tab, bg=T["panel"])
        extra_row.pack(fill="x", padx=10, pady=4)
        self._btn("🔍 Find Duplicates",   extra_row,
                   lambda: self._run(lambda: find_duplicate_files()), w=20).pack(side="left")
        self._btn("📂 Remove Empty Folders", extra_row,
                   lambda: self._run(lambda: remove_empty_folders()), w=24).pack(side="left", padx=6)
        self._btn("📋 Prefetch Analyzer",  extra_row,
                   lambda: self._run(analyze_prefetch), w=20).pack(side="left")

        self._refresh_history()

    def _refresh_history(self):
        self.history_list.delete(0, "end")
        history = _ba_tracker.all_history()
        if not history:
            self.history_list.insert("end", "  (Chua co lich su nao)")
            self.history_canvas.delete("all")
            return

        freed_list = []
        for entry in history:
            ts    = entry.get("ts", "?")
            label = entry.get("label", "?")
            total_gained = sum(
                max(d.get("gained", 0), 0)
                for d in entry.get("drives", {}).values()
            )
            freed_list.append(total_gained)
            line = f"  {ts}  [{label}]  +{fmt_bytes(total_gained)}"
            self.history_list.insert("end", line)

        # Mini bar chart
        self._draw_history_chart(freed_list[-20:])
        self.hist_session_var.set(
            f"Phien nay: {_session.summary()}"
        )

    def _draw_history_chart(self, values: list):
        T   = self._T
        c = self.history_canvas
        c.delete("all")
        if not values:
            return
        T       = self._T
        w       = c.winfo_width() or 460
        h       = 75
        padding = 10
        n       = len(values)
        max_v   = max(values) or 1
        bar_w   = max(4, (w - 2 * padding) // n - 2)

        for i, v in enumerate(values):
            bh  = int((v / max_v) * (h - 20))
            x0  = padding + i * (bar_w + 2)
            x1  = x0 + bar_w
            y0  = h - bh
            y1  = h
            pct = v / max_v
            color = T["green"] if pct > 0.5 else (T["yellow"] if pct > 0.2 else T["accent"])
            c.create_rectangle(x0, y0, x1, y1, fill=color, outline="")
            if n <= 10:
                c.create_text(
                    (x0 + x1) // 2, h + 2,
                    text=fmt_bytes(v).replace(" ", ""),
                    font=("Segoe UI", 6), fill=T["fg_dim"], anchor="n"
                )

    def _clear_ba_history(self):
        if messagebox.askyesno("Clear", "Xoa toan bo lich su before/after?"):
            _ba_tracker._data["history"] = []
            _ba_tracker._save()
            self._refresh_history()
            ok("Da xoa lich su")

    # ── Notification handler ─────────────────────────────────────────────────
    def _on_notification(self, item: dict):
        """Duoc goi khi co thong bao moi – cap nhat badge tren tab."""
        self._safe_after(self._update_notif_badge)

    def _update_notif_badge(self):
        n = _notif.unread_count()
        if n > 0 and hasattr(self, "_notif_label"):
            self._notif_label.configure(text=f" 🔔 {n} ")

    # ── Tab: Monitor (v9) – Real-time CPU / RAM graphs ────────────────────────
    def _build_tab_monitor(self, nb):
        T   = self._T
        T   = self._T
        tab = self._tab(nb, "📡 Monitor")

        tk.Label(tab, text="Real-time CPU & RAM (cap nhat moi giay)",
                 font=("Segoe UI", 9), bg=T["panel"], fg=T["fg_dim"]).pack(
                 anchor="w", padx=10, pady=(8, 2))

        # Current values row
        vals_row = tk.Frame(tab, bg=T["panel"])
        vals_row.pack(fill="x", padx=10, pady=2)
        self._mon_cpu_var = tk.StringVar(value="CPU:  0%")
        self._mon_ram_var = tk.StringVar(value="RAM:  0%")
        self._mon_net_var = tk.StringVar(value="Net:  0 KB/s ↑  0 KB/s ↓")
        for var, col in [
            (self._mon_cpu_var, T["accent"]),
            (self._mon_ram_var, T["green"]),
            (self._mon_net_var, T["accent2"]),
        ]:
            tk.Label(vals_row, textvariable=var, bg=T["panel"], fg=col,
                     font=("Consolas", 10, "bold"), width=26).pack(side="left", padx=4)

        # CPU canvas
        tk.Label(tab, text="CPU %", font=("Segoe UI", 8, "bold"),
                 bg=T["panel"], fg=T["fg_dim"]).pack(anchor="w", padx=10)
        self._cpu_canvas = tk.Canvas(tab, bg=T["log_bg"], height=90, bd=0,
                                      highlightthickness=1,
                                      highlightbackground=T["border"])
        self._cpu_canvas.pack(fill="x", padx=10, pady=(0, 4))

        # RAM canvas
        tk.Label(tab, text="RAM %", font=("Segoe UI", 8, "bold"),
                 bg=T["panel"], fg=T["fg_dim"]).pack(anchor="w", padx=10)
        self._ram_canvas = tk.Canvas(tab, bg=T["log_bg"], height=90, bd=0,
                                      highlightthickness=1,
                                      highlightbackground=T["border"])
        self._ram_canvas.pack(fill="x", padx=10, pady=(0, 4))

        # Net canvas
        tk.Label(tab, text="Network KB/s (↑ Sent  ↓ Recv)",
                 font=("Segoe UI", 8, "bold"),
                 bg=T["panel"], fg=T["fg_dim"]).pack(anchor="w", padx=10)
        self._net_canvas = tk.Canvas(tab, bg=T["log_bg"], height=70, bd=0,
                                      highlightthickness=1,
                                      highlightbackground=T["border"])
        self._net_canvas.pack(fill="x", padx=10, pady=(0, 6))

        # Temperature
        self._mon_temp_var = tk.StringVar(value="Temp: --")
        tk.Label(tab, textvariable=self._mon_temp_var, bg=T["panel"],
                 fg=T["yellow"], font=("Segoe UI", 9)).pack(anchor="w", padx=10)

        # Controls
        ctrl = tk.Frame(tab, bg=T["panel"])
        ctrl.pack(fill="x", padx=10, pady=4)
        self._btn("📊 Snapshot to Report", ctrl,
                   lambda: self._run(lambda: _notif.push("Monitor snapshot saved","ok")),
                   color=T["accent2"], w=22).pack(side="left")
        self._btn("🌡 Check Temps", ctrl,
                   lambda: self._run(self._do_check_temps), w=14).pack(side="left", padx=6)

        # Monitor loop se duoc kich hoat boi _on_tab_changed khi nguoi dung chon tab nay
        # KHONG goi _monitor_loop() truc tiep o day de tranh loop ngam khi tab chua duoc hien thi
        self._monitor_active = False

    def _on_tab_changed(self, event=None):
        """
        [PATCHED v2] Bat/Tat vong lap ve do thi dua tren tab hien tai.
        Neu nguoi dung chuyen sang tab khac, vong lap bi ngat de tiet kiem CPU.
        """
        try:
            current_text = self._nb.tab(self._nb.select(), "text")
            is_monitor_tab = "Monitor" in current_text or "📡" in current_text
            if is_monitor_tab:
                if not getattr(self, "_monitor_active", False):
                    self._monitor_active = True
                    self._monitor_loop()
            else:
                self._monitor_active = False  # Ngat vong lap, sau(1000) se khong goi tiep
        except Exception:
            pass

    def _monitor_loop(self):
        """
        Refresh bieu do moi 1 giay.
        [PATCHED v2] Chi chay khi _monitor_active=True va cua so con song (_alive).
        Vong lap tu dong dung khi nguoi dung chuyen sang tab khac.
        """
        if not getattr(self, '_monitor_active', False) or not getattr(self, '_alive', True):
            return
        snap = _metrics.snapshot()
        cpu  = snap["cpu"]
        ram  = snap["ram"]
        sent = snap["net_sent"]
        recv = snap["net_recv"]

        # Update labels
        last_cpu  = cpu[-1]  if cpu  else 0
        last_ram  = ram[-1]  if ram  else 0
        last_sent = sent[-1] if sent else 0
        last_recv = recv[-1] if recv else 0
        self._mon_cpu_var.set(f"CPU:  {last_cpu:.0f}%")
        self._mon_ram_var.set(f"RAM:  {last_ram:.0f}%")
        self._mon_net_var.set(
            f"Net:  {last_sent:.0f} KB/s ↑   {last_recv:.0f} KB/s ↓"
        )

        # Draw graphs
        self._draw_line_graph(self._cpu_canvas, cpu,
                               self._T["accent"],  0, 100, label="CPU %")
        self._draw_line_graph(self._ram_canvas, ram,
                               self._T["green"],   0, 100, label="RAM %")
        # Net graph (combined)
        max_net = max(max(sent + recv + [1]), 1)
        self._draw_dual_line_graph(self._net_canvas, sent, recv,
                                    self._T["accent2"], self._T["yellow"],
                                    0, max_net)

        # Chi lap lai neu dieu kien an toan van thoa man
        if self._monitor_active and self._alive:
            self.after(1000, self._monitor_loop)

    def _blend_color(self, hex_color: str, alpha: float = 0.25) -> str:
        """
        Pha mau hex_color voi mau nen (log_bg) theo ty le alpha.
        Tra ve mau solid hop le voi tkinter (khong dung RGBA 8 chu so).
        """
        try:
            bg = self._T["log_bg"].lstrip("#")
            fg = hex_color.lstrip("#")
            if len(bg) != 6 or len(fg) != 6:
                return hex_color
            br, bg2, bb = int(bg[0:2],16), int(bg[2:4],16), int(bg[4:6],16)
            fr, fg2, fb = int(fg[0:2],16), int(fg[2:4],16), int(fg[4:6],16)
            r = int(br + (fr - br) * alpha)
            g = int(bg2 + (fg2 - bg2) * alpha)
            b = int(bb + (fb - bb) * alpha)
            return f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            return hex_color

    def _draw_line_graph(self, canvas, values, color, vmin, vmax, label=""):
        """Ve bieu do duong tren Canvas."""
        T   = self._T
        canvas.delete("all")
        w  = canvas.winfo_width()  or 460
        h  = canvas.winfo_height() or 90
        n  = len(values)
        if n < 2:
            return
        canvas.create_rectangle(0, 0, w, h, fill=T["log_bg"], outline="")
        # Grid lines at 25, 50, 75%
        for pct in [25, 50, 75]:
            y_g = h - int((pct - vmin) / max(vmax - vmin, 1) * h)
            canvas.create_line(0, y_g, w, y_g, fill=T["border"], dash=(2, 4))
            canvas.create_text(3, y_g - 6, text=f"{pct}%",
                                font=("Segoe UI", 6), fill=T["fg_dim"], anchor="w")
        # Fill area under curve – dung mau solid pha voi nen thay vi RGBA
        fill_color = self._blend_color(color, alpha=0.22)
        pts  = []
        step = w / max(n - 1, 1)
        for i, v in enumerate(values):
            x = int(i * step)
            y = h - int((v - vmin) / max(vmax - vmin, 1) * (h - 4))
            pts.append((x, y))
        if pts:
            poly = [pts[0][0], h] + [c for p in pts for c in p] + [pts[-1][0], h]
            canvas.create_polygon(poly, fill=fill_color, outline="")
            # Line on top
            for i in range(len(pts) - 1):
                canvas.create_line(pts[i][0], pts[i][1], pts[i+1][0], pts[i+1][1],
                                    fill=color, width=2, smooth=True)
        # Current value badge
        last_val = values[-1] if values else 0
        badge_color = (T["red"] if last_val > 85
                       else T["yellow"] if last_val > 60
                       else T["green"])
        canvas.create_text(w - 4, 6, text=f"{last_val:.0f}%",
                            font=("Consolas", 9, "bold"), fill=badge_color, anchor="ne")

    def _draw_dual_line_graph(self, canvas, vals1, vals2, col1, col2, vmin, vmax):
        canvas.delete("all")
        T = self._T
        w = canvas.winfo_width()  or 460
        h = canvas.winfo_height() or 70
        canvas.create_rectangle(0, 0, w, h, fill=T["log_bg"], outline="")
        for vals, col in [(vals1, col1), (vals2, col2)]:
            n    = len(vals)
            if n < 2:
                continue
            step = w / max(n - 1, 1)
            pts  = []
            for i, v in enumerate(vals):
                x = int(i * step)
                y = h - int((v - vmin) / max(vmax - vmin, 1) * (h - 4))
                pts.append((x, y))
            for i in range(len(pts) - 1):
                canvas.create_line(pts[i][0], pts[i][1], pts[i+1][0], pts[i+1][1],
                                    fill=col, width=2, smooth=True)
        # Legend
        canvas.create_text(4,  8, text="↑ Sent", fill=col1, font=("Segoe UI",7), anchor="w")
        canvas.create_text(4, 18, text="↓ Recv", fill=col2, font=("Segoe UI",7), anchor="w")

    def _do_check_temps(self):
        temps = get_temperatures()
        zones = temps.get("zones", [])
        if zones:
            avg = round(sum(zones)/len(zones), 1)
            hot = any(t > 85 for t in zones)
            text = f"Temp: {avg}°C avg | Zones: {zones[:4]}"
            self._mon_temp_var.set(text)
            if hot:
                warn(f"NHIET DO CAO: {max(zones)}°C !")
            else:
                ok(text)
        else:
            self._mon_temp_var.set("Temp: Khong doc duoc (BIOS WMI chua ho tro)")

    # ── Tab: Services (v9) ────────────────────────────────────────────────────
    def _build_tab_services(self, nb):
        T   = self._T
        T   = self._T
        tab = self._tab(nb, "🔩 Services")

        ctrl = tk.Frame(tab, bg=T["panel"])
        ctrl.pack(fill="x", padx=8, pady=(8, 2))
        tk.Label(ctrl, text="Windows Services:", font=("Segoe UI", 9, "bold"),
                 bg=T["panel"], fg=T["fg"]).pack(side="left")

        self._svc_filter = tk.StringVar(value="all")
        for label, val in [("All","all"),("Running","running"),("Stopped","stopped")]:
            tk.Radiobutton(ctrl, text=label, variable=self._svc_filter, value=val,
                           bg=T["panel"], fg=T["fg"], selectcolor=T["border"],
                           activebackground=T["panel"], font=("Segoe UI",8),
                           command=self._refresh_services).pack(side="left", padx=4)
        self._btn("🔄 Refresh", ctrl, self._refresh_services, w=10).pack(side="left", padx=6)

        # Search bar
        search_row = tk.Frame(tab, bg=T["panel"])
        search_row.pack(fill="x", padx=8, pady=(0,2))
        tk.Label(search_row, text="Search:", bg=T["panel"], fg=T["fg"],
                 font=("Segoe UI",8)).pack(side="left")
        self._svc_search = tk.StringVar()
        self._svc_search.trace("w", lambda *a: self._filter_services())
        tk.Entry(search_row, textvariable=self._svc_search, width=24,
                 bg=T["entry_bg"], fg=T["fg"], insertbackground=T["fg"],
                 font=("Segoe UI",9)).pack(side="left", padx=4)

        # Treeview
        tree_frame = tk.Frame(tab, bg=T["panel"])
        tree_frame.pack(fill="both", expand=True, padx=8, pady=2)
        sb = tk.Scrollbar(tree_frame, bg=T["panel"], troughcolor=T["bg"])
        style = ttk.Style()
        style.configure("Svc.Treeview",
                         background=T["log_bg"], foreground=T["fg"],
                         fieldbackground=T["log_bg"], rowheight=18,
                         font=("Consolas",8))
        style.configure("Svc.Treeview.Heading",
                         background=T["border"], foreground=T["accent"],
                         font=("Segoe UI",8,"bold"))
        style.map("Svc.Treeview",
                   background=[("selected",T["accent"])],
                   foreground=[("selected",T["bg"])])
        self._svc_tree = ttk.Treeview(
            tree_frame, columns=("Name","Display","State"), show="headings",
            yscrollcommand=sb.set, style="Svc.Treeview", height=14
        )
        sb.config(command=self._svc_tree.yview)
        for col, w_col in [("Name",140),("Display",220),("State",80)]:
            self._svc_tree.heading(col, text=col)
            self._svc_tree.column(col, width=w_col, anchor="w")
        self._svc_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        # Action buttons
        btn_row = tk.Frame(tab, bg=T["panel"])
        btn_row.pack(fill="x", padx=8, pady=(4,6))
        self._btn("▶ Start",   btn_row,
                   lambda: self._svc_action("start"),  color=T["green"], w=10).pack(side="left")
        self._btn("⏹ Stop",   btn_row,
                   lambda: self._svc_action("stop"),   color=T["yellow"], w=10).pack(side="left", padx=4)
        self._btn("🚫 Disable",btn_row,
                   lambda: self._svc_action("disable"),color=T["red"],    w=10).pack(side="left")
        self._btn("✅ Auto",   btn_row,
                   lambda: self._svc_action("auto"),   color=T["accent"], w=10).pack(side="left", padx=4)

        self._all_services_data = []
        self._refresh_services()

    def _refresh_services(self):
        def _do():
            filt = self._svc_filter.get()
            state = None if filt == "all" else filt
            svcs  = get_all_services(filter_state=state)
            self._safe_after(lambda s=svcs: self._populate_svc_tree(s))
        threading.Thread(target=_do, daemon=True).start()

    def _populate_svc_tree(self, svcs):
        self._all_services_data = svcs
        self._filter_services()

    def _filter_services(self):
        search = self._svc_search.get().lower()
        self._svc_tree.delete(*self._svc_tree.get_children())
        for s in self._all_services_data:
            name    = s.get("name","")
            display = s.get("display","")
            state   = s.get("state","")
            if search and search not in name.lower() and search not in display.lower():
                continue
            tag = "running" if state == "running" else "stopped"
            self._svc_tree.insert("","end",
                values=(name, display, state), tags=(tag,))
        self._svc_tree.tag_configure("running", foreground=self._T["green"])
        self._svc_tree.tag_configure("stopped", foreground=self._T["fg_dim"])

    def _svc_action(self, action: str):
        sel = self._svc_tree.selection()
        if not sel:
            messagebox.showinfo("Services", "Chua chon service nao.")
            return
        for item in sel:
            vals = self._svc_tree.item(item,"values")
            if not vals:
                continue
            name = vals[0]
            def _do(n=name, a=action):
                if a == "start":    sc_start(n)
                elif a == "stop":   sc_stop(n)
                elif a == "disable": sc_config_start(n,"disabled")
                elif a == "auto":   sc_config_start(n,"auto")
                ok(f"Service {a}: {n}")
            self._run(_do)
        self.after(1500, self._refresh_services)

    # ── Tab: Hosts (v9) ───────────────────────────────────────────────────────
    def _build_tab_hosts(self, nb):
        T   = self._T
        T   = self._T
        tab = self._tab(nb, "🌍 Hosts")

        tk.Label(tab, text=f"Hosts file: {HOSTS_PATH}",
                 font=("Segoe UI", 8), bg=T["panel"], fg=T["fg_dim"]).pack(
                 anchor="w", padx=10, pady=(8, 2))

        # Editor
        edit_frame = tk.Frame(tab, bg=T["panel"])
        edit_frame.pack(fill="both", expand=True, padx=10, pady=4)
        sb = tk.Scrollbar(edit_frame, bg=T["panel"], troughcolor=T["bg"])
        self._hosts_editor = tk.Text(
            edit_frame, bg=T["entry_bg"], fg=T["fg"], font=("Consolas", 8),
            insertbackground=T["fg"], yscrollcommand=sb.set,
            wrap="none", bd=0,
            highlightthickness=1, highlightbackground=T["border"]
        )
        sb.config(command=self._hosts_editor.yview)
        self._hosts_editor.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        # Action buttons
        btn_row = tk.Frame(tab, bg=T["panel"])
        btn_row.pack(fill="x", padx=10, pady=(4, 6))
        self._btn("📂 Load",           btn_row, self._load_hosts_file,       w=10).pack(side="left")
        self._btn("💾 Save",           btn_row, self._save_hosts_file,
                   color=T["green"], w=10).pack(side="left", padx=4)
        self._btn("🚫 Add Ad Block",   btn_row,
                   lambda: self._run(add_ad_block_to_hosts),
                   color=T["red"], w=16).pack(side="left")
        self._btn("↩ Remove Ad Block", btn_row,
                   lambda: self._run(remove_ad_block_from_hosts),
                   color=T["yellow"], w=18).pack(side="left", padx=4)
        self._btn("🔄 Reload",         btn_row, self._load_hosts_file,       w=10).pack(side="left")

        self._load_hosts_file()

    def _load_hosts_file(self):
        content = read_hosts()
        self._hosts_editor.delete("1.0", "end")
        self._hosts_editor.insert("end", content)

    def _save_hosts_file(self):
        content = self._hosts_editor.get("1.0", "end")
        self._run(lambda: write_hosts(content))

    # ── Tab: Plugins (v9) ─────────────────────────────────────────────────────
    def _build_tab_plugins(self, nb):
        T   = self._T
        T   = self._T
        tab = self._tab(nb, "🧩 Plugins")

        hdr_row = tk.Frame(tab, bg=T["panel"])
        hdr_row.pack(fill="x", padx=10, pady=(8, 2))
        tk.Label(hdr_row, text="Plugins trong thu muc: " + PLUGIN_DIR,
                 font=("Segoe UI", 8), bg=T["panel"], fg=T["fg_dim"]).pack(side="left")
        self._btn("🔄 Reload Plugins", hdr_row,
                   lambda: self._run(self._reload_plugins_ui), w=16).pack(side="right")
        self._btn("📂 Open Folder",    hdr_row,
                   lambda: os.startfile(PLUGIN_DIR), w=14).pack(side="right", padx=4)

        # Plugin list
        list_frame = tk.Frame(tab, bg=T["panel"])
        list_frame.pack(fill="both", expand=True, padx=10, pady=4)
        sb = tk.Scrollbar(list_frame, bg=T["panel"], troughcolor=T["bg"])
        self._plugin_list = tk.Listbox(
            list_frame, yscrollcommand=sb.set, bg=T["log_bg"], fg=T["fg"],
            font=("Consolas", 9), bd=0, selectbackground=T["accent"],
            selectforeground=T["bg"],
            highlightthickness=1, highlightbackground=T["border"], height=10
        )
        sb.config(command=self._plugin_list.yview)
        self._plugin_list.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        # Notification / unread badge
        notif_frame = tk.LabelFrame(tab, text=" Notification Center ",
                                     bg=T["panel"], fg=T["accent"],
                                     font=("Segoe UI", 9, "bold"), bd=1)
        notif_frame.pack(fill="x", padx=10, pady=(4, 2))
        nb2 = tk.Scrollbar(notif_frame, bg=T["panel"], troughcolor=T["bg"])
        self._notif_list = tk.Listbox(
            notif_frame, yscrollcommand=nb2.set, bg=T["log_bg"], fg=T["fg"],
            font=("Consolas", 8), bd=0, height=5,
            highlightthickness=1, highlightbackground=T["border"]
        )
        nb2.config(command=self._notif_list.yview)
        self._notif_list.pack(side="left", fill="both", expand=True, padx=4, pady=4)
        nb2.pack(side="right", fill="y")

        notif_btns = tk.Frame(tab, bg=T["panel"])
        notif_btns.pack(fill="x", padx=10)
        self._notif_label = tk.Label(notif_btns, text="", bg=T["panel"],
                                      fg=T["yellow"], font=("Segoe UI",9,"bold"))
        self._notif_label.pack(side="left")
        self._btn("🔄 Refresh",   notif_btns, self._refresh_notifs,              w=10).pack(side="left", padx=4)
        self._btn("🗑 Clear All",  notif_btns, lambda: [_notif.clear(), self._refresh_notifs()],
                   color=T["red"], w=10).pack(side="left")

        # Plugin action buttons
        btn_row = tk.Frame(tab, bg=T["panel"])
        btn_row.pack(fill="x", padx=10, pady=(4, 6))
        self._btn("▶ Run Selected Plugin", btn_row,
                   self._run_selected_plugin, color=T["green"], w=22).pack(side="left")
        self._btn("▶▶ Run All Plugins",    btn_row,
                   lambda: self._run(self._run_all_plugins),
                   color=T["accent2"], w=18).pack(side="left", padx=6)

        self._populate_plugins_list()
        self._refresh_notifs()

    def _populate_plugins_list(self):
        self._plugin_list.delete(0, "end")
        if not self._plugins:
            self._plugin_list.insert("end", "  (Chua co plugin nao. Dat file .py vao thu muc plugins/)")
            return
        for p in self._plugins:
            self._plugin_list.insert("end",
                f"  🧩 {p['name']:<30}  {p.get('desc','')[:40]}")

    def _reload_plugins_ui(self):
        self._plugins = load_plugins()
        self._safe_after(self._populate_plugins_list)
        ok(f"Loaded {len(self._plugins)} plugins")

    def _run_selected_plugin(self):
        idx = self._plugin_list.curselection()
        if not idx or not self._plugins:
            messagebox.showinfo("Plugins", "Chua chon plugin nao.")
            return
        i = idx[0]
        if i < len(self._plugins):
            self._run(lambda p=self._plugins[i]: run_plugin(p))

    def _run_all_plugins(self):
        for p in self._plugins:
            run_plugin(p)

    def _refresh_notifs(self):
        self._notif_list.delete(0, "end")
        icon_map = {"ok":"✅","warn":"⚠","err":"❌","info":"ℹ"}
        for item in _notif.all()[:30]:
            icon = icon_map.get(item.get("level","info"),"ℹ")
            ts   = item.get("ts","")[-8:]  # HH:MM:SS
            msg  = item.get("msg","")[:60]
            self._notif_list.insert("end", f"  {icon} [{ts}] {msg}")
        n = _notif.unread_count()
        self._notif_label.configure(
            text=f" 🔔 {n} thong bao moi " if n else ""
        )

    # ── Updated _run_and_report to use v4 report ──────────────────────────────
    def _run_and_report(self, fn):
        if self._running:
            messagebox.showwarning("Dang chay", "Mot tac vu dang chay, vui long cho.")
            return
        self._running = True
        self._update_progress(0, "Dang chay Full Cleaner...")
        _ba_tracker.snapshot_before()

        def _worker():
            try:
                t0      = time.time()
                si      = get_full_sysinfo()
                results = fn(self.settings)
                duration = round(time.time() - t0, 1)

                for r in results:
                    _session.add(r)

                entry = _ba_tracker.snapshot_after("Full Cleaner")
                if entry:
                    ba_text = "  ✅ " + entry["ts"] + "  |  " + "  ".join(
                        f"{k}: +{fmt_bytes(max(v['gained'],0))}"
                        for k, v in entry.get("drives",{}).items()
                    )
                    self._safe_after(lambda t=ba_text: self._ba_label.set(t))

                # Metrics snapshot
                m_snap = _metrics.snapshot()

                # Plugin results
                p_results = [
                    {"name": p["name"],
                     "freed": run_plugin(p).get("freed",0),
                     "notes": run_plugin(p).get("notes","")}
                    for p in self._plugins
                ] if self._plugins else []

                report_path = generate_html_report_v4(
                    results, si, duration, "Full Cleaner",
                    ba_entry=entry,
                    metrics_snapshot=m_snap,
                    plugin_results=p_results if p_results else None,
                )
                self._safe_after(lambda: webbrowser.open(report_path))

                total_freed = sum(r.freed for r in results if hasattr(r,"freed"))
                _show_balloon(
                    "WinOptimizer – Hoan thanh!",
                    f"Don dep xong trong {duration}s – {fmt_bytes(total_freed)} da giai phong"
                )
                self._refresh_sysinfo()
            except Exception as exc:
                err(f"Loi: {exc}")
                log(traceback.format_exc(), "error")
            finally:
                self._running = False
                self._safe_after(lambda: self._update_progress(0, t("app_ready")))
        self._thread = threading.Thread(target=_worker, daemon=True)
        self._thread.start()

    # ── Tab: Startup Manager ─────────────────────────────────────────────────
    def _build_tab_startup(self, nb):
        T = self._T
        tab = self._tab(nb, t("tab_startup"))
        tk.Label(tab, text="Quan ly chuong trinh khoi dong cung Windows",
                 font=("Segoe UI",9), bg=T["panel"], fg=T["fg_dim"]).pack(padx=10, pady=(8,4), anchor="w")

        cols = tk.Frame(tab, bg=T["panel"])
        cols.pack(fill="both", expand=True, padx=10, pady=4)

        sb = tk.Scrollbar(cols, orient="vertical", bg=T["panel"], troughcolor=T["bg"])
        self.startup_list = tk.Listbox(
            cols, yscrollcommand=sb.set, selectmode="extended",
            bg=T["log_bg"], fg=T["fg"], font=("Consolas",8), bd=0,
            highlightthickness=1, highlightbackground=T["border"],
            selectbackground=T["accent"], selectforeground=T["bg"]
        )
        sb.config(command=self.startup_list.yview)
        self.startup_list.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        btn_row = tk.Frame(tab, bg=T["panel"])
        btn_row.pack(fill="x", padx=10, pady=(4,8))
        self._btn("Refresh", btn_row, self._refresh_startup_list).pack(side="left")
        self._btn("Disable Selected", btn_row, self._disable_startup_selected, color=T["yellow"]).pack(side="left", padx=4)
        self._btn("Restore All", btn_row, lambda: self._run(restore_startup_items), color=T["green"]).pack(side="left")

        # Game Prep
        tk.Frame(tab, bg=T["border"], height=1).pack(fill="x", padx=10, pady=4)
        tk.Label(tab, text="Game Prep – dong app nen truoc khi choi game:",
                 font=("Segoe UI",9,"bold"), bg=T["panel"], fg=T["fg"]).pack(anchor="w", padx=10)
        self._btn("Chay Game Prep", tab, self._run_game_prep, color=T["green"]).pack(padx=10, pady=4, anchor="w")
        self._startup_entries = []
        self._refresh_startup_list()

    def _refresh_startup_list(self):
        self._startup_entries = enumerate_startup_entries()
        self.startup_list.delete(0, "end")
        for item in self._startup_entries:
            if item["kind"] == "reg":
                label = f"[REG ] {item['name'][:40]:40}  {item['source']}"
            else:
                label = f"[FILE] {item['name'][:40]:40}  {item['source']}"
            self.startup_list.insert("end", label)

    def _disable_startup_selected(self):
        idxs = self.startup_list.curselection()
        if not idxs:
            messagebox.showinfo("Startup", "Chua chon item nao.")
            return
        data = load_backup()
        done = 0
        for idx in idxs:
            item = self._startup_entries[idx]
            if disable_startup_item(item, data):
                done += 1
                ok(f"Disabled startup: {item['name']}")
            else:
                warn(f"Khong the disable: {item['name']}")
        save_backup(data)
        ok(f"Da tat {done} startup item")
        self._refresh_startup_list()

    def _run_game_prep(self):
        T = self._T
        found = game_prep()
        if not found:
            return
        names = [label for _, label in found]
        win = tk.Toplevel(self)
        win.title("Game Prep")
        win.configure(bg=T["panel"])
        win.geometry("360x300")
        tk.Label(win, text="Chon app de dong:", font=("Segoe UI",10,"bold"),
                 bg=T["panel"], fg=T["fg"]).pack(pady=(12,4))
        lb = tk.Listbox(win, selectmode="extended", bg=T["log_bg"], fg=T["fg"],
                         font=("Segoe UI",9), bd=0, height=10,
                         selectbackground=T["accent"])
        for n in names:
            lb.insert("end", n)
        lb.pack(fill="both", expand=True, padx=10)
        lb.select_set(0, "end")
        def _do():
            idxs     = lb.curselection()
            selected = [found[i] for i in idxs]
            win.destroy()
            self._run(lambda: _kill_processes(selected))
        btn_row = tk.Frame(win, bg=T["panel"])
        btn_row.pack(pady=8)
        self._btn("Dong App Da Chon", btn_row, _do, color=T["red"]).pack(side="left", padx=4)
        self._btn("Huy", btn_row, win.destroy).pack(side="left")

    # ── Tab: Schedule ─────────────────────────────────────────────────────────
    def _build_tab_schedule(self, nb):
        T = self._T
        tab = self._tab(nb, t("tab_schedule"))
        tk.Label(tab, text="Tu Dong Don Dep Hang Ngay",
                 font=("Segoe UI",11,"bold"), bg=T["panel"], fg=T["fg"]).pack(pady=(12,6))

        info_text = (
            "Len lich chay Full Cleaner tu dong hang ngay vao gio ban chon.\n"
            "Script se duoc dang ky vao Windows Task Scheduler.\n"
            "Can quyen Administrator."
        )
        tk.Label(tab, text=info_text, bg=T["panel"], fg=T["fg_dim"],
                 font=("Segoe UI",9), justify="left", wraplength=360).pack(padx=16, anchor="w")

        row1 = tk.Frame(tab, bg=T["panel"])
        row1.pack(padx=16, pady=10, anchor="w")
        tk.Label(row1, text="Gio chay (HH:MM):", bg=T["panel"], fg=T["fg"],
                 font=("Segoe UI",9)).pack(side="left")
        self.sched_time_var = tk.StringVar(value=self.settings.get("schedule_time","03:00"))
        tk.Entry(row1, textvariable=self.sched_time_var, width=8,
                 bg=T["log_bg"], fg=T["fg"], insertbackground=T["fg"],
                 font=("Segoe UI",10)).pack(side="left", padx=6)

        row2 = tk.Frame(tab, bg=T["panel"])
        row2.pack(padx=16, pady=4, anchor="w")
        tk.Label(row2, text="Task Name:", bg=T["panel"], fg=T["fg"],
                 font=("Segoe UI",9)).pack(side="left")
        self.sched_name_var = tk.StringVar(value=self.settings.get("schedule_task_name","WinOptimizerUltimate_AutoClean"))
        tk.Entry(row2, textvariable=self.sched_name_var, width=36,
                 bg=T["log_bg"], fg=T["fg"], insertbackground=T["fg"],
                 font=("Segoe UI",9)).pack(side="left", padx=6)

        self.sched_status_var = tk.StringVar(value="")
        tk.Label(tab, textvariable=self.sched_status_var, bg=T["panel"],
                 fg=T["green"], font=("Segoe UI",9,"bold")).pack(padx=16, anchor="w")

        btn_row = tk.Frame(tab, bg=T["panel"])
        btn_row.pack(padx=16, pady=12, anchor="w")
        self._btn("✅ Bat Len Lich", btn_row, self._enable_schedule, color=T["green"], w=18).pack(side="left")
        self._btn("❌ Xoa Lich",     btn_row, self._disable_schedule, color=T["red"],   w=14).pack(side="left", padx=4)
        self._btn("🔍 Kiem Tra",     btn_row, self._check_schedule,   w=12).pack(side="left")

        tk.Frame(tab, bg=T["border"], height=1).pack(fill="x", padx=16, pady=12)
        tk.Label(tab, text="Chay ngay bay gio:", font=("Segoe UI",9,"bold"),
                 bg=T["panel"], fg=T["fg_dim"]).pack(anchor="w", padx=16)
        self._btn("▶ Chay Full Cleaner Ngay", tab,
                  lambda: self._run_and_report(full_cleaner), color=T["accent"]).pack(padx=16, pady=4, anchor="w")

        last = self.settings.get("last_run")
        if last:
            tk.Label(tab, text=f"Lan cuoi chay: {last}", bg=T["panel"],
                     fg=T["fg_dim"], font=("Segoe UI",8)).pack(anchor="w", padx=16, pady=(8,0))

    def _enable_schedule(self):
        t_str = self.sched_time_var.get().strip()
        name  = self.sched_name_var.get().strip()
        if not re.match(r"^\d{2}:\d{2}$", t_str):
            messagebox.showerror("Loi", "Gio khong hop le. Dung dinh dang HH:MM (vi du 03:00)")
            return
        self.settings["schedule_time"]      = t_str
        self.settings["schedule_task_name"] = name
        save_settings(self.settings)
        def _do():
            ok_ = schedule_auto_clean(t_str, name)
            if ok_:
                self.sched_status_var.set(f"✅ Da len lich luc {t_str} hang ngay")
            else:
                self.sched_status_var.set("❌ Len lich that bai – xem log")
        self._run(_do)

    def _disable_schedule(self):
        name = self.sched_name_var.get().strip()
        def _do():
            ok_ = remove_schedule(name)
            self.sched_status_var.set("✅ Da xoa lich" if ok_ else "⚠ Khong tim thay lich nay")
        self._run(_do)

    def _check_schedule(self):
        name = self.sched_name_var.get().strip()
        exists = check_schedule_exists(name)
        self.sched_status_var.set(
            f"✅ Lich '{name}' DANG HOAT DONG" if exists
            else f"❌ Lich '{name}' chua duoc tao"
        )

    # ── Tab: Settings ─────────────────────────────────────────────────────────
    def _build_tab_settings(self, nb):
        T = self._T
        tab = self._tab(nb, t("tab_settings"))
        tk.Label(tab, text="Tuy Chon", font=("Segoe UI",11,"bold"),
                 bg=T["panel"], fg=T["fg"]).pack(pady=(12,8), padx=10, anchor="w")

        self._setting_vars = {}
        bool_settings = [
            ("auto_restore_point",    "Tao restore point truoc khi tweak"),
            ("auto_backup_before_tweak","Backup registry truoc khi tweak"),
            ("confirm_before_extreme", "Xac nhan truoc khi chay Extreme profile"),
            ("clean_temp",            "Cleaner: Temp & Prefetch"),
            ("clean_browser",         "Cleaner: Browser Cache"),
            ("clean_game",            "Cleaner: Game Cache"),
            ("clean_office",          "Cleaner: Office & App Cache"),
            ("clean_devtools",        "Cleaner: Dev Tools Cache"),
            ("clean_system_files",    "Cleaner: System Files"),
            ("clean_recycle",         "Cleaner: Recycle Bin & Thumbs"),
            ("clean_security",        "Cleaner: Security & Privacy"),
            ("clean_old_downloads",   "Cleaner: Old Downloads (>30d)"),
            ("optimize_network",      "Full Cleaner: Network Optimize"),
            ("optimize_drives",       "Full Cleaner: Drive Optimize"),
        ]
        frame = tk.Frame(tab, bg=T["panel"])
        frame.pack(fill="both", expand=True, padx=10)
        for key, label in bool_settings:
            var = tk.BooleanVar(value=self.settings.get(key, True))
            self._setting_vars[key] = var
            ttk.Checkbutton(frame, text=label, variable=var,
                             command=self._save_settings_from_ui).pack(anchor="w", pady=1)

        tk.Frame(tab, bg=T["border"], height=1).pack(fill="x", padx=10, pady=8)
        btn_row = tk.Frame(tab, bg=T["panel"])
        btn_row.pack(fill="x", padx=10, pady=(0,4))
        self._btn("Luu Settings", btn_row, self._save_settings_from_ui, color=T["green"], w=14).pack(side="left")
        self._btn("📤 Export", btn_row, self._export_settings_ui, w=10).pack(side="left", padx=4)
        self._btn("📥 Import", btn_row, self._import_settings_ui, w=10).pack(side="left")

        extra_row = tk.Frame(tab, bg=T["panel"])
        extra_row.pack(fill="x", padx=10, pady=(2,2))
        self._btn("🌐 VI / EN Language", extra_row,
                   self._toggle_language, w=20).pack(side="left")
        self._btn("🕐 Auto-Profile By Time", extra_row,
                   lambda: self._run(lambda: auto_profile_by_time(self.settings)),
                   color=T["accent2"], w=22).pack(side="left", padx=6)

        extra_row2 = tk.Frame(tab, bg=T["panel"])
        extra_row2.pack(fill="x", padx=10, pady=(0, 4))
        self._btn("📋 Register Context Menu", extra_row2,
                   lambda: self._run(register_context_menu),
                   color=T["green"], w=24).pack(side="left")
        self._btn("✖ Remove Context Menu", extra_row2,
                   lambda: self._run(unregister_context_menu),
                   color=T["red"], w=24).pack(side="left", padx=6)

        # Power plan quick switcher
        pwr_frame = tk.LabelFrame(tab, text=" Power Plan Quick Switch ",
                                   bg=T["panel"], fg=T["accent"],
                                   font=("Segoe UI",9,"bold"), bd=1)
        pwr_frame.pack(fill="x", padx=10, pady=(4,6))
        pwr_row = tk.Frame(pwr_frame, bg=T["panel"])
        pwr_row.pack(fill="x", padx=6, pady=4)
        self._pwr_plan_var = tk.StringVar(value="-- Loading --")
        self._pwr_plan_combo = ttk.Combobox(
            pwr_row, textvariable=self._pwr_plan_var,
            width=38, state="readonly", font=("Segoe UI",9)
        )
        self._pwr_plan_combo.pack(side="left")
        self._btn("Apply", pwr_row,
                   self._apply_selected_power_plan, w=8).pack(side="left", padx=4)
        self._btn("🔄", pwr_row, self._refresh_power_plans, w=4).pack(side="left")
        self._power_plan_data = []
        self._refresh_power_plans()

    def _save_settings_from_ui(self):
        for key, var in self._setting_vars.items():
            self.settings[key] = var.get()
        save_settings(self.settings)
        ok("Settings da duoc luu")

    def _export_settings_ui(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON","*.json"),("All","*.*")],
            initialfile="winoptimizer_settings.json"
        )
        if path:
            export_settings(path)

    def _import_settings_ui(self):
        path = filedialog.askopenfilename(
            filetypes=[("JSON","*.json"),("All","*.*")]
        )
        if path and import_settings(path):
            self.settings = load_settings()
            for key, var in self._setting_vars.items():
                var.set(self.settings.get(key, True))
            messagebox.showinfo("Import", "Settings da duoc nhap thanh cong.")

    # ── Tab: Processes (v7) ───────────────────────────────────────────────────
    def _build_tab_processes(self, nb):
        T   = self._T
        T   = self._T
        tab = self._tab(nb, t("tab_processes"))

        ctrl = tk.Frame(tab, bg=T["panel"])
        ctrl.pack(fill="x", padx=8, pady=(8, 2))
        tk.Label(ctrl, text="Top processes theo RAM:", font=("Segoe UI", 9, "bold"),
                 bg=T["panel"], fg=T["fg"]).pack(side="left")
        self._btn("🔄 Refresh", ctrl, self._refresh_processes, w=10).pack(side="left", padx=6)
        self._btn("❌ Kill Selected", ctrl, self._kill_selected_process,
                   color=self._T["red"], w=14).pack(side="left")
        tk.Label(ctrl, text="  (auto refresh 10s)",
                 font=("Segoe UI", 8), bg=T["panel"], fg=T["fg_dim"]).pack(side="left")

        cols_frame = tk.Frame(tab, bg=T["panel"])
        cols_frame.pack(fill="both", expand=True, padx=8, pady=(2, 6))

        # Treeview
        cols = ("PID", "Name", "RAM (MB)", "Status")
        style = ttk.Style()
        style.configure("Proc.Treeview",
                         background=T["log_bg"], foreground=T["fg"],
                         fieldbackground=T["log_bg"], rowheight=20,
                         font=("Consolas", 8))
        style.configure("Proc.Treeview.Heading",
                         background=T["border"], foreground=T["accent"],
                         font=("Segoe UI", 8, "bold"))
        style.map("Proc.Treeview",
                   background=[("selected", T["accent"])],
                   foreground=[("selected", T["bg"])])

        sb = tk.Scrollbar(cols_frame, bg=T["panel"], troughcolor=T["bg"])
        self.proc_tree = ttk.Treeview(
            cols_frame, columns=cols, show="headings",
            yscrollcommand=sb.set, style="Proc.Treeview", height=16
        )
        sb.config(command=self.proc_tree.yview)
        for col, w in zip(cols, [60, 220, 90, 100]):
            self.proc_tree.heading(col, text=col,
                                    command=lambda c=col: self._sort_proc_tree(c))
            self.proc_tree.column(col, width=w, anchor="w")
        self.proc_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        # RAM summary bar
        self.proc_ram_var = tk.StringVar(value="")
        tk.Label(tab, textvariable=self.proc_ram_var, bg=T["panel"],
                 fg=T["accent"], font=("Segoe UI", 8)).pack(anchor="w", padx=8, pady=(0,4))

        self._proc_sort_col = "RAM (MB)"
        self._proc_sort_rev = True
        self._refresh_processes()
        self._schedule_proc_refresh()

    def _refresh_processes(self):
        def _do():
            procs = get_top_processes(25)
            ram   = get_ram_usage()
            self._safe_after(lambda: self._populate_proc_tree(procs, ram))
        threading.Thread(target=_do, daemon=True).start()

    def _populate_proc_tree(self, procs, ram):
        T = self._T
        for item in self.proc_tree.get_children():
            self.proc_tree.delete(item)
        for p in procs:
            tag = "high" if p["mem_mb"] > 500 else ("med" if p["mem_mb"] > 100 else "")
            self.proc_tree.insert("", "end",
                values=(p["pid"], p["name"], p["mem_mb"], p.get("status","")),
                tags=(tag,))
        self.proc_tree.tag_configure("high", foreground=self._T["red"])
        self.proc_tree.tag_configure("med",  foreground=self._T["yellow"])
        self.proc_ram_var.set(
            f"RAM: {ram['used']}GB / {ram['total']}GB  ({ram['pct']}% used)  |  Free: {ram['free']}GB"
        )

    def _sort_proc_tree(self, col):
        items = [(self.proc_tree.set(k, col), k) for k in self.proc_tree.get_children("")]
        try:
            items.sort(key=lambda x: float(x[0]), reverse=self._proc_sort_rev)
        except ValueError:
            items.sort(key=lambda x: x[0], reverse=self._proc_sort_rev)
        for idx, (_, k) in enumerate(items):
            self.proc_tree.move(k, "", idx)
        self._proc_sort_rev = not self._proc_sort_rev

    def _kill_selected_process(self):
        sel = self.proc_tree.selection()
        if not sel:
            messagebox.showinfo("Kill", "Chua chon process nao.")
            return
        for item in sel:
            vals = self.proc_tree.item(item, "values")
            if vals:
                pid  = int(vals[0])
                name = vals[1]
                if messagebox.askyesno("Kill Process", f"Kill '{name}' (PID {pid})?"):
                    if kill_process(pid):
                        ok(f"Killed: {name} (PID {pid})")
                    else:
                        warn(f"Khong kill duoc: {name}")
        self._refresh_processes()

    def _schedule_proc_refresh(self):
        """Tu dong refresh process list moi 10 giay neu tab dang active."""
        def _check():
            try:
                if self._nb.tab(self._nb.select(), "text").startswith("📊"):
                    self._refresh_processes()
            except Exception:
                pass
            self.after(10000, _check)
        self.after(10000, _check)

    # ── Tab: Network (v7) ─────────────────────────────────────────────────────
    def _build_tab_network(self, nb):
        T   = self._T
        T   = self._T
        tab = self._tab(nb, t("tab_network"))

        # Adapter info
        ada_frame = tk.LabelFrame(tab, text=" Network Adapters ", bg=T["panel"],
                                   fg=T["accent"], font=("Segoe UI", 9, "bold"), bd=1)
        ada_frame.pack(fill="x", padx=10, pady=(10, 4))
        self.adapter_label = tk.StringVar(value="  Chua tai...")
        tk.Label(ada_frame, textvariable=self.adapter_label,
                 bg=T["panel"], fg=T["fg"], font=("Consolas", 8),
                 justify="left", wraplength=460).pack(anchor="w", padx=8, pady=4)
        self._btn("🔄 Refresh Adapters", ada_frame, self._refresh_adapters, w=18).pack(padx=8, pady=4)

        # Ping test
        ping_frame = tk.LabelFrame(tab, text=" Ping Test ", bg=T["panel"],
                                    fg=T["accent"], font=("Segoe UI", 9, "bold"), bd=1)
        ping_frame.pack(fill="x", padx=10, pady=4)
        ping_ctrl = tk.Frame(ping_frame, bg=T["panel"])
        ping_ctrl.pack(fill="x", padx=8, pady=4)
        self._btn("▶ Run Ping Test", ping_ctrl,
                   lambda: self._run(self._do_ping_test), color=T["green"], w=16).pack(side="left")
        self.ping_results_var = tk.StringVar(value="")
        tk.Label(ping_frame, textvariable=self.ping_results_var,
                 bg=T["panel"], fg=T["fg"], font=("Consolas", 8),
                 justify="left").pack(anchor="w", padx=8, pady=(0,4))

        # DNS benchmark
        dns_frame = tk.LabelFrame(tab, text=" DNS Benchmark ", bg=T["panel"],
                                   fg=T["accent"], font=("Segoe UI", 9, "bold"), bd=1)
        dns_frame.pack(fill="x", padx=10, pady=4)
        dns_ctrl = tk.Frame(dns_frame, bg=T["panel"])
        dns_ctrl.pack(fill="x", padx=8, pady=4)
        self._btn("▶ Benchmark DNS", dns_ctrl,
                   lambda: self._run(self._do_dns_bench), color=T["accent"], w=16).pack(side="left")
        self.dns_results_var = tk.StringVar(value="")
        self._best_dns_ip    = None
        tk.Label(dns_frame, textvariable=self.dns_results_var,
                 bg=T["panel"], fg=T["fg"], font=("Consolas", 8),
                 justify="left").pack(anchor="w", padx=8)
        self.apply_dns_btn = self._btn("⚡ Apply Fastest DNS", dns_frame,
                                        self._apply_fastest_dns, color=T["green"], w=22)
        self.apply_dns_btn.pack(padx=8, pady=(0,6), anchor="w")

        # Driver check
        drv_frame = tk.LabelFrame(tab, text=" Driver Checker ", bg=T["panel"],
                                   fg=T["accent"], font=("Segoe UI", 9, "bold"), bd=1)
        drv_frame.pack(fill="x", padx=10, pady=(4,8))
        drv_ctrl = tk.Frame(drv_frame, bg=T["panel"])
        drv_ctrl.pack(fill="x", padx=8, pady=4)
        self._btn("🔍 Check Outdated Drivers", drv_ctrl,
                   lambda: self._run(lambda: check_outdated_drivers(365)),
                   color=T["yellow"], w=26).pack(side="left")
        if IS_WIN11:
            self._btn("🪟 Win11 Tweaks", drv_ctrl,
                       lambda: self._run(optimize_win11_tweaks),
                       color=T["accent2"], w=16).pack(side="left", padx=8)

        self._refresh_adapters()

    def _refresh_adapters(self):
        T = self._T
        def _do():
            adapters = get_network_adapters()
            lines = []
            for a in adapters[:4]:
                name = a.get("Name","?")[:40]
                ip   = a.get("ip","N/A")
                mac  = a.get("MACAddress","N/A")
                spd_raw = a.get("Speed","0")
                try:
                    spd_mbps = int(spd_raw or "0") // 1_000_000
                    spd = f"{spd_mbps}Mbps" if spd_mbps else "?"
                except Exception:
                    spd = "?"
                lines.append(f"  {name}\n    IP: {ip}  |  MAC: {mac}  |  Speed: {spd}")
            text = "\n".join(lines) if lines else "  (Khong phat hien adapter)"
            self._safe_after(lambda: self.adapter_label.set(text))
        threading.Thread(target=_do, daemon=True).start()

    def _do_ping_test(self):
        results = ping_test()
        lines = []
        for r in results:
            icon = "✅" if r["ok"] else "❌"
            ms   = f"{r['avg_ms']}ms" if r["avg_ms"] else "timeout"
            loss = f"{r['loss_pct']}% loss"
            lines.append(f"  {icon} {r['host']:<22} {ms:>8}  {loss}")
        self._safe_after(lambda: self.ping_results_var.set("\n".join(lines)))

    def _do_dns_bench(self):
        results = dns_benchmark()
        lines = []
        for i, r in enumerate(results):
            icon = "🥇" if i == 0 else "  "
            ms   = f"{r['avg_ms']}ms" if r["avg_ms"] else "fail"
            lines.append(f"  {icon} {r['name']:<12} ({r['server']})  {ms:>8}")
        self._safe_after(lambda: self.dns_results_var.set("\n".join(lines)))
        if results and results[0].get("ok"):
            self._best_dns_ip = results[0]["server"]
        else:
            self._best_dns_ip = None

    def _apply_fastest_dns(self):
        if not self._best_dns_ip:
            messagebox.showinfo("DNS", "Chua co ket qua benchmark. Chay Benchmark DNS truoc.")
            return
        self._run(lambda: apply_best_dns(self._best_dns_ip))

    # ── Thread-safe UI call ──────────────────────────────────────────────────
    def _ui_call(self, fn):
        """
        Thread-safe: queue a callable to run on the main thread.
        Use this instead of self.after() from background threads.
        """
        self._ui_queue.put(fn)

    def _pump_ui_queue(self):
        """
        Doc ca hai hang doi tren Main Thread moi 50ms.
        - self._ui_queue  : cac lambda GUI noi bo (an toan da co)
        - ui_log_queue    : (tag, line) hoac ('__progress__', (pct, label))
                            duoc _emit() / _set_progress() day vao tu luong nen
        [PATCH - Loi #2] Dam bao Thread-Safety tuyet doi cho Tkinter.
        """
        # 1) xu ly hang doi noi bo (lambda)
        try:
            while True:
                fn = self._ui_queue.get_nowait()
                try:
                    fn()
                except Exception as exc:
                    log(f"UI queue (internal) error: {exc}", "error")
        except _queue.Empty:
            pass

        # 2) xu ly hang doi log / progress toan cuc tu _emit() va _set_progress()
        try:
            while True:
                item = ui_log_queue.get_nowait()
                try:
                    tag, payload = item
                    if tag == "__progress__":
                        pct, label = payload
                        self._update_progress(pct, label)
                    else:
                        self._append_log(tag, payload)
                except Exception as exc:
                    log(f"UI queue (log) error: {exc}", "error")
        except _queue.Empty:
            pass

        self.after(50, self._pump_ui_queue)

    # ── Helper: bind hotkeys ─────────────────────────────────────────────────
    def _bind_hotkeys(self):
        self.bind_all("<Control-r>", lambda e: self._refresh_sysinfo())
        self.bind_all("<Control-R>", lambda e: self._refresh_sysinfo())
        self.bind_all("<Control-c>", lambda e: self._clear_log())
        self.bind_all("<Control-C>", lambda e: self._clear_log())
        self.bind_all("<Control-q>", lambda e: self._on_close())
        self.bind_all("<Control-Q>", lambda e: self._on_close())
        self.bind_all("<F5>",        lambda e: self._refresh_sysinfo())
        self.bind_all("<F1>",        lambda e: self._show_help())

    def _show_help(self):
        T   = self._T
        T   = self._T
        win = tk.Toplevel(self)
        win.title("Help – F1")
        win.configure(bg=T["panel"])
        win.geometry("460x380")
        win.resizable(False, False)
        tk.Label(win, text=f"📖  {APP_NAME} Help",
                 font=("Segoe UI", 12, "bold"), bg=T["panel"], fg=T["accent"]).pack(pady=(14, 6))
        helps = [
            ("Ctrl+R / F5", "Refresh thong tin he thong"),
            ("Ctrl+C",      "Xoa Activity Log"),
            ("Ctrl+Q",      "Thoat chuong trinh"),
            ("F1",          "Mo cua so Help nay"),
            ("⚡ Optimize",  "Chon profile toi uu hoa"),
            ("🧹 Cleaner",   "Don dep thu cong tung module"),
            ("🔧 Tools",     "RAM / Disk / SSD / Hibernate"),
            ("📊 Processes", "Quan ly process dang chay"),
            ("🌐 Network",   "Ping / DNS benchmark"),
            ("🎛 Tweaks",    "Bat/tat tung registry tweak"),
            ("📈 Benchmark", "Do toc do CPU / RAM / Disk"),
            ("📋 History",   "Lich su don dep truoc/sau"),
            ("⏰ Schedule",  "Dat lich tu dong hang ngay"),
            ("⚙ Settings",  "Cau hinh cac module"),
        ]
        frame = tk.Frame(win, bg=T["panel"])
        frame.pack(fill="both", expand=True, padx=16, pady=4)
        for i, (key, desc) in enumerate(helps):
            bg = T["log_bg"] if i % 2 == 0 else T["panel"]
            row = tk.Frame(frame, bg=bg)
            row.pack(fill="x")
            tk.Label(row, text=f"  {key:<20}", bg=bg, fg=T["accent"],
                     font=("Consolas", 9), width=22, anchor="w").pack(side="left")
            tk.Label(row, text=desc, bg=bg, fg=T["fg"],
                     font=("Segoe UI", 9), anchor="w").pack(side="left", padx=4)
        self._btn("OK", win, win.destroy, w=10).pack(pady=10)

    def _toggle_language(self):
        global _LANG
        _LANG = "en" if _LANG == "vi" else "vi"
        self.settings["language"] = _LANG
        save_settings(self.settings)
        messagebox.showinfo("Language", f"Da chuyen sang: {'Tieng Anh' if _LANG=='en' else 'Tieng Viet'}.\n"
                            "Khoi dong lai app de ap dung day du.")

    def _refresh_power_plans(self):
        def _do():
            plans = list_all_power_plans()
            self._power_plan_data = plans
            names = [f"{'★ ' if p.get('active') else '  '}{p['name'][:40]}  [{p['guid'][:8]}]"
                     for p in plans]
            active_idx = next((i for i,p in enumerate(plans) if p.get("active")), 0)
            self._safe_after(lambda: [
                self._pwr_plan_combo.configure(values=names),
                self._pwr_plan_combo.current(active_idx) if names else None,
            ])
        threading.Thread(target=_do, daemon=True).start()

    def _apply_selected_power_plan(self):
        idx = self._pwr_plan_combo.current()
        if idx < 0 or idx >= len(self._power_plan_data):
            return
        plan = self._power_plan_data[idx]
        self._run(lambda: switch_power_plan(plan["guid"]))
        self.after(1500, self._refresh_power_plans)

    # ── Theme toggle ─────────────────────────────────────────────────────────
    def _toggle_theme(self):
        self._theme = "light" if self._theme == "dark" else "dark"
        self.settings["theme"] = self._theme
        save_settings(self.settings)
        self._theme_btn_text.set("☀ Light" if self._theme == "dark" else "🌙 Dark")
        messagebox.showinfo(
            "Theme",
            f"Da chuyen sang theme '{self._theme}'.\n"
            "Khoi dong lai ung dung de ap dung day du."
        )

    # ── Minimize to tray ────────────────────────────────────────────────────
    def _minimize_to_tray(self):
        self.withdraw()
        if self._tray_win is not None:
            return
        tray = tk.Toplevel()
        tray.withdraw()
        tray.title("WinOptimizer Tray")
        self._tray_win = tray
        ok("Da thu nho xuong system tray. Nhan 'Show' de mo lai.")

        def _restore():
            self.deiconify()
            self.lift()
            self.focus_force()
            tray.destroy()
            self._tray_win = None

        def _tray_menu(event=None):
            menu = tk.Menu(tray, tearoff=0,
                            bg=self._T["panel"], fg=self._T["fg"],
                            activebackground=self._T["accent"],
                            activeforeground=self._T["bg"])
            menu.add_command(label="Show",              command=_restore)
            menu.add_command(label="Full Cleaner Now",  command=lambda: [_restore(), self._run_and_report(full_cleaner)])
            menu.add_separator()
            menu.add_command(label="Quit",              command=self._on_close)
            try:
                menu.tk_popup(tray.winfo_pointerx(), tray.winfo_pointery())
            finally:
                menu.grab_release()

        # Tray placeholder window (taskbar icon stays hidden)
        tray.bind("<Button-3>", _tray_menu)
        tray.bind("<Double-Button-1>", lambda e: _restore())
        tray.deiconify()
        tray.geometry("1x1+0+0")
        tray.attributes("-alpha", 0.01)
        tray.attributes("-topmost", True)

    # ── What's new splash ───────────────────────────────────────────────────
    def _show_whats_new(self):
        T   = self._T
        win = tk.Toplevel(self)
        win.title(f"Moi trong v{APP_VERSION}")
        win.configure(bg=T["panel"])
        win.geometry("500x440")
        win.resizable(False, False)
        win.grab_set()

        tk.Label(win, text=f"🎉  Chào mừng đến với v{APP_VERSION}!",
                 font=("Segoe UI", 13, "bold"), bg=T["panel"], fg=T["accent"]).pack(pady=(18, 6))

        notes = [
            ("📊 Tab Processes",    "Top process theo RAM/CPU, Kill ngay trong app"),
            ("🌐 Tab Network",      "Ping test, DNS benchmark, apply DNS nhanh nhat"),
            ("🔍 Driver Checker",   "Liet ke driver co the loi thoi"),
            ("⬇ System Tray",       "Thu nho xuong tray, chay ngam nen"),
            ("🌙 Dark/Light Theme", "Toggle theme ngan gon tren thanh tieu de"),
            ("📈 Before/After",     "So sanh dung luong dia truoc/sau don dep"),
            ("🪟 Win11 Tweaks",      "Tat Widgets, Cortana chat, Start suggestions"),
            ("⌨ Hotkeys",           "Ctrl+R Refresh  |  Ctrl+C Clear  |  Ctrl+Q Thoat"),
            ("🌡 Temp Monitor",     "Theo doi nhiet do CPU (neu BIOS ho tro WMI)"),
            ("⭐ Extra Tweaks v6",   "20+ registry tweak moi (TCP, Explorer, Input)"),
        ]
        frame = tk.Frame(win, bg=T["panel"])
        frame.pack(fill="both", expand=True, padx=20, pady=4)
        for i, (title, desc) in enumerate(notes):
            bg_row = T["log_bg"] if i % 2 == 0 else T["panel"]
            row = tk.Frame(frame, bg=bg_row)
            row.pack(fill="x")
            tk.Label(row, text=f"  {title:<22}", bg=bg_row, fg=T["accent"],
                     font=("Segoe UI", 9, "bold"), width=24, anchor="w").pack(side="left")
            tk.Label(row, text=desc, bg=bg_row, fg=T["fg"],
                     font=("Segoe UI", 9), anchor="w").pack(side="left", padx=4)

        self._btn("OK – Bắt Đầu!", win, win.destroy, color=T["green"], w=20).pack(pady=14)

    # ── Tab: Sysinfo (override to add Before/After history) ────────────────
    def _build_tab_sysinfo(self, nb):
        T = self._T
        tab = self._tab(nb, t("tab_info"))
        self.sysinfo_text = scrolledtext.ScrolledText(
            tab, bg=T["log_bg"], fg=T["fg"], font=("Consolas",8),
            state="disabled", wrap="word", bd=0,
            highlightthickness=1, highlightbackground=T["border"]
        )
        self.sysinfo_text.pack(fill="both", expand=True, padx=6, pady=6)
        btn_row = tk.Frame(tab, bg=T["panel"])
        btn_row.pack(fill="x", padx=6, pady=(0,6))
        self._btn("Refresh", btn_row, self._refresh_sysinfo).pack(side="left")
        self._btn("Quick Report", btn_row, lambda: self._run(quick_report)).pack(side="left", padx=4)
        self._btn("Full Report Bundle", btn_row, lambda: self._run(self._gen_report_bundle)).pack(side="left", padx=4)

    def _refresh_sysinfo(self):
        def _do():
            si = get_full_sysinfo()
            ag, an = get_active_power_scheme()
            sched_exists = check_schedule_exists(self.settings.get("schedule_task_name","WinOptimizerUltimate_AutoClean"))
            lines = [
                f"{APP_NAME} {APP_SUBTITLE}",
                "─" * 50,
                f"OS      : {si['os_caption']}",
                f"Version : {si['os_version']}  Build {si['os_build']}",
                f"Python  : {si['python']}",
                "",
                f"CPU     : {si['cpu_name']}",
                f"         Cores {si['cpu_cores']} / Logical {si['cpu_logical']} @ {si['cpu_mhz']} MHz",
                f"RAM     : {si['ram_gb']} GB",
            ]
            for g in si["gpus"]:
                lines.append(f"GPU     : {g['name']} | Driver {g['driver']} | VRAM {g['vram_mb']}MB")
            used  = round(si["total_c_gb"] - si["free_c_gb"], 1)
            pct   = int(used*100/si["total_c_gb"]) if si["total_c_gb"] else 0
            lines += [
                "",
                f"O C:    : {si['total_c_gb']} GB total | {used} GB used ({pct}%) | {si['free_c_gb']} GB free",
                f"Drives  : {', '.join(si['drives'])}",
                "",
                f"Battery : {'Co' if si['has_battery'] else 'Khong'}",
                f"Power   : {si['ac_power'] and 'AC' or 'DC/Unknown'}",
                f"Plan    : {an or 'Unknown'} ({ag or '?'})",
                "",
                f"Schedule: {'ACTIVE' if sched_exists else 'Not set'}",
                f"Last run: {self.settings.get('last_run') or 'Never'}",
                "",
                f"─── Phien Lam Viec Hien Tai ───",
                _session.summary(),
            ]
            if IS_WIN7:
                lines.append("\n⚠ Windows 7 het ho tro bao mat tu 01/2020!")
            if IS_WIN10_PLUS and date.today() > WIN10_EOS:
                lines.append("\n⚠ Windows 10 het ho tro tu 14/10/2025!")
            text = "\n".join(lines)
            self._safe_after(lambda: self._set_sysinfo_text(text))
        threading.Thread(target=_do, daemon=True).start()

    def _set_sysinfo_text(self, text: str):
        self.sysinfo_text.configure(state="normal")
        self.sysinfo_text.delete("1.0","end")
        self.sysinfo_text.insert("end", text)
        self.sysinfo_text.configure(state="disabled")

    def _gen_report_bundle(self):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        folder = os.path.join(REPORT_DIR, ts)
        os.makedirs(folder, exist_ok=True)
        energy_out    = os.path.join(folder, "energy.html")
        sysinfo_out   = os.path.join(folder, "systeminfo.txt")
        # [PATCHED] Dung list args - khong shell=True, khong f-string vao shell
        run_cmd(
            ["powercfg", "/energy", "/output", energy_out, "/duration", "60"],
            shell=False, timeout=180
        )
        # systeminfo khong ho tro redirect trong list mode -> dung capture va ghi file
        ok2, sysinfo_text, _ = run_cmd(["systeminfo"], shell=False, timeout=120)
        if ok2 and sysinfo_text:
            try:
                with open(sysinfo_out, "w", encoding="utf-8") as f_:
                    f_.write(sysinfo_text)
            except Exception as exc:
                warn(f"Khong ghi duoc systeminfo.txt: {exc}")
        try:
            os.startfile(folder)
        except Exception:
            pass
        ok(f"Report bundle: {folder}")

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _tab(self, nb, label) -> tk.Frame:
        T = self._T
        f = tk.Frame(nb, bg=T["panel"], padx=4, pady=4)
        nb.add(f, text=label)
        return f

    def _btn(self, text, parent, cmd, color=None, w=None):
        T = self._T
        if color is None:
            color = T["accent"]
        kwargs = dict(text=text, command=cmd,
                      bg=T["border"], fg=color,
                      activebackground=T["panel"], activeforeground=color,
                      font=("Segoe UI", 9), relief="flat", cursor="hand2",
                      padx=10, pady=4, bd=0)
        if w:
            kwargs["width"] = w
        return tk.Button(parent, **kwargs)

    def _append_log(self, tag: str, line: str):
        def _do():
            self.log_box.configure(state="normal")
            ts = datetime.now().strftime("%H:%M:%S")
            self.log_box.insert("end", f"[{ts}] {line}\n", tag)
            self.log_box.see("end")
            self.log_box.configure(state="disabled")
        self._safe_after(_do)

    def _update_progress(self, pct: int, label: str):
        def _do():
            self.progress_var.set(pct)
            self.progress_label.set(label)
        self._safe_after(_do)

    def _clear_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0","end")
        self.log_box.configure(state="disabled")

    def _open_latest_report(self):
        if not os.path.isdir(REPORT_DIR):
            messagebox.showinfo("Bao cao", "Chua co bao cao nao.")
            return
        reports = sorted(
            [f for f in os.listdir(REPORT_DIR) if f.endswith(".html")],
            reverse=True
        )
        if not reports:
            messagebox.showinfo("Bao cao", "Chua co bao cao HTML nao.")
            return
        webbrowser.open(os.path.join(REPORT_DIR, reports[0]))

    def _run(self, fn):
        if self._running:
            messagebox.showwarning("Dang chay", "Mot tac vu dang chay, vui long cho.")
            return
        self._running = True
        self._update_progress(0, "Dang chay...")
        def _worker():
            try:
                fn()
            except Exception as exc:
                err(f"Loi: {exc}")
                log(traceback.format_exc(), "error")
            finally:
                self._running = False
                self._safe_after(lambda: self._update_progress(0, "San sang"))
        self._thread = threading.Thread(target=_worker, daemon=True)
        self._thread.start()

    def _run_and_report(self, fn):
        if self._running:
            messagebox.showwarning("Dang chay", "Mot tac vu dang chay, vui long cho.")
            return
        self._running = True
        self._update_progress(0, "Dang chay Full Cleaner...")
        _ba_tracker.snapshot_before()

        def _worker():
            try:
                t0   = time.time()
                si   = get_full_sysinfo()
                results = fn(self.settings)
                duration = round(time.time() - t0, 1)
                # Track session
                for r in results:
                    _session.add(r)
                # Before/After snapshot
                entry = _ba_tracker.snapshot_after("Full Cleaner")
                if entry:
                    lines = []
                    for drive, d in entry.get("drives", {}).items():
                        gained = d.get("gained", 0)
                        lines.append(
                            f"  {drive}: +{fmt_bytes(max(gained,0))} giai phong "
                            f"(Con {fmt_bytes(d['after_free'])} trong)"
                        )
                    ba_text = f"  ✅ {entry['ts']}  |  " + "  ".join(
                        f"{k}: +{fmt_bytes(max(v['gained'],0))}"
                        for k, v in entry.get("drives",{}).items()
                    )
                    self._safe_after(lambda t=ba_text: self._ba_label.set(t))

                report_path = generate_html_report_v3(
                    results, si, duration, "Full Cleaner",
                    ba_entry=entry
                )
                self._safe_after(lambda: webbrowser.open(report_path))
                total_freed = sum(r.freed for r in results if hasattr(r, "freed"))
                _show_balloon(
                    "WinOptimizer – Hoan thanh!",
                    f"Don dep xong trong {duration}s – {fmt_bytes(total_freed)} da giai phong"
                )
                self._refresh_sysinfo()
            except Exception as exc:
                err(f"Loi: {exc}")
                log(traceback.format_exc(), "error")
            finally:
                self._running = False
                self._safe_after(lambda: self._update_progress(0, "San sang"))
        self._thread = threading.Thread(target=_worker, daemon=True)
        self._thread.start()


    def _safe_after(self, fn):
        """Thread-safe wrapper: only calls self.after() if GUI is still alive."""
        if not getattr(self, "_alive", False):
            return
        try:
            self.after(0, fn)
        except RuntimeError:
            pass  # "main thread is not in main loop" – GUI shutting down

    def _on_close(self):
        if self._running:
            if not messagebox.askyesno("Thoat", "Dang chay tac vu. Ban co chac muon thoat?"):
                return
        self._alive = False
        _metrics.stop()
        try:
            self.destroy()
        except Exception:
            pass

# =============================================================================
#  CLI MENU  (fallback khi khong co tkinter hoac dung --cli)
# =============================================================================
def _cli_monitor_snap():
    snap = _metrics.snapshot()
    cpu_v = snap["cpu"]
    ram_v = snap["ram"]
    info(f"CPU: {cpu_v[-1]:.0f}% (avg {sum(cpu_v)/len(cpu_v):.0f}%)  "
         f"RAM: {ram_v[-1]:.0f}% (avg {sum(ram_v)/len(ram_v):.0f}%)")

def _cli_list_services():
    svcs = get_all_services("running")
    for s in svcs[:20]:
        info(f"  {s['name']:<25} {s.get('display','')}")
    info(f"Total running: {len(svcs)}")


def cli_menu():
    s = load_settings()
    while True:
        print()
        print(f"\033[96;1m{'─'*72}\033[0m")
        print(f"  {APP_NAME}  {APP_SUBTITLE}")
        print(f"\033[96;1m{'─'*72}\033[0m")
        print("\033[95;1m  PROFILES\033[0m")
        print("[1] Auto Tune          [2] Gaming Plus        [3] Competitive Extreme")
        print("[4] Desktop Max        [5] Laptop Turbo       [A] Everyday Safe")
        print("\033[95;1m  CLEANER\033[0m")
        print("[C] Full Cleaner       [T] Temp & Prefetch    [B] Browser Cache")
        print("[G] Game Cache         [O] Office & App       [D] Dev Tools")
        print("[W] Windows Store      [Y] System Files       [Z] Recycle+Thumbs")
        print("[N] Network Optimize   [L] Old Downloads      [V] Drive Optimize")
        print("[EL] Event Log Clean   [FC] Font Cache Rebuild")
        print("\033[95;1m  TWEAKS\033[0m")
        print("[R] Registry Gaming    [M] Mouse Precision    [E] Visual Effects")
        print("[K] Low-Latency Reg    [H] HAGS               [J] Network Reg Tweaks")
        print("[EX] Extra Tweaks v6   [TW] Apply All Tweaks v8")
        print("[S] Service Trim       [X] Service Trim+      [TK] Task Trim")
        print("\033[95;1m  TOOLS (v6+)\033[0m")
        print("[RAM] RAM Cleanup      [DA] Disk Analyzer     [TR] SSD TRIM")
        print("[PF-P] Pagefile Smart  [HI] Hibernate OFF     [HON] Hibernate ON")
        print("\033[95;1m  ANALYSIS (v8)\033[0m")
        print("[BM] Full Benchmark    [BT] Boot Time         [DF] Duplicate Files")
        print("[EF] Empty Folders     [PF] Prefetch Analyze  [AP] Auto-Profile by Time")
        print("\033[95;1m  HEALTH\033[0m")
        print("[SF] SFC /scannow      [DM] DISM RestoreHealth [CC] Component Cleanup")
        print("\033[95;1m  MISC\033[0m")
        print("[I] Quick Report       [P] Restore Point      [RT] Restore All")
        print("[SC] Schedule Setup    [SS] Session Stats     [Q] Quit")
        choice = input("\nChon: ").strip().upper()

        dispatch = {
            "1":  lambda: auto_tune(s),
            "2":  lambda: gaming_plus_profile(s),
            "3":  lambda: competitive_profile(s),
            "4":  lambda: desktop_max_profile(s),
            "5":  lambda: laptop_profile(s),
            "A":  lambda: safe_everyday_profile(s),
            "C":  lambda: full_cleaner(s),
            "T":  cleanup_temp_files,
            "B":  cleanup_browser_cache,
            "G":  cleanup_game_cache,
            "O":  cleanup_office_and_apps,
            "D":  cleanup_dev_tools,
            "W":  cleanup_store_cache,
            "Y":  cleanup_system_files,
            "Z":  cleanup_recycle_and_thumbs,
            "N":  optimize_network,
            "L":  cleanup_old_downloads,
            "V":  optimize_drives,
            "R":  optimize_gaming_registry,
            "M":  optimize_mouse,
            "E":  optimize_visuals,
            "K":  optimize_low_latency_registry,
            "H":  enable_hags,
            "J":  optimize_network_registry,
            "S":  lambda: apply_service_trim(False),
            "X":  lambda: apply_service_trim(True),
            "TK": apply_task_trim,
            "SF": run_sfc,
            "DM": run_dism_restore,
            "CC": run_component_cleanup,
            "I":  quick_report,
            "P":  create_restore_point,
            "RT": restore_all,
            "SC": lambda: _cli_schedule(),
            # v6 new
            "EL":  cleanup_event_logs,
            "FC":  rebuild_font_cache,
            "EX":  optimize_extra_tweaks,
            "RAM": cleanup_ram,
            "DA":  lambda: analyze_disk_space(),
            "TR":  run_ssd_trim,
            "PF":  lambda: optimize_pagefile("smart"),
            "HI":  lambda: toggle_hibernation(False),
            "HON": lambda: toggle_hibernation(True),
            "SS":  lambda: print(f"\n  {_session.summary()}"),
            # v8 new
            "BM":  lambda: ok(str(run_full_benchmark())),
            "DF":  lambda: find_duplicate_files(),
            "EF":  lambda: remove_empty_folders(),
            "PF":  lambda: analyze_prefetch(),
            "BT":  lambda: info(str(get_startup_boot_time())),
            "TW":  lambda: [apply_tweak(item[0], True) for item in ALL_TWEAKS],
            "AP":  lambda: auto_profile_by_time(),
            # v9 new
            "MON": lambda: _cli_monitor_snap(),
            "CTX": register_context_menu,
            "UCX": unregister_context_menu,
            "UPD": check_for_updates,
            "HST": add_ad_block_to_hosts,
            "HRM": remove_ad_block_from_hosts,
            "SDL": reduce_startup_delay,
            "PLG": lambda: [load_plugins(), [run_plugin(p) for p in _loaded_plugins]],
            "SVC": lambda: _cli_list_services(),
        }
        if choice == "Q":
            break
        fn = dispatch.get(choice)
        if fn:
            try:
                fn()
            except Exception as exc:
                err(f"Loi: {exc}")
                log(traceback.format_exc(), "error")
            input("\nNhan Enter de tiep tuc...")
        else:
            warn("Lua chon khong hop le")

def _cli_schedule():
    print("\n[1] Bat len lich")
    print("[2] Xoa lich")
    print("[3] Kiem tra lich")
    c = input("Chon: ").strip()
    s = load_settings()
    name = s.get("schedule_task_name", "WinOptimizerUltimate_AutoClean")
    if c == "1":
        t = input(f"Gio chay HH:MM [{s.get('schedule_time','03:00')}]: ").strip() or s.get("schedule_time","03:00")
        schedule_auto_clean(t, name)
    elif c == "2":
        remove_schedule(name)
    elif c == "3":
        exists = check_schedule_exists(name)
        info(f"Lich '{name}': {'HOAT DONG' if exists else 'chua tao'}")

# =============================================================================
#  ENTRY POINT
# =============================================================================
def startup_banner():
    os.system("color" if platform.system() == "Windows" else "")
    w = 72
    print(f"\n\033[96;1m+{'='*w}+")
    print(f"|  {APP_NAME}  –  {APP_SUBTITLE}".ljust(w+1) + "|")
    print(f"+{'='*w}+\033[0m")
    cap, ver, build = get_os_caption_and_build()
    info(f"OS : {cap} | Ver {ver} | Build {build}")
    if IS_WIN7:
        info("Mode: Windows 7 (Game Mode/HAGS/Store bo qua)")
        warn("Win7 het ho tro bao mat tu 01/2020. Nen nang cap!")
    elif IS_WIN10_PLUS:
        info("Mode: Windows 10/11 – day du tinh nang")
        if date.today() > WIN10_EOS:
            warn("Win10 het ho tro tu 14/10/2025. Nen nang cap!")
    else:
        info("Mode: Windows 8/8.1 (mot so tinh nang Win10 bo qua)")

def main():
    _setup_logging()

    if platform.system() != "Windows":
        print("Script nay chi chay tren Windows.")
        return 1

    ensure_admin()
    ensure_dirs()

    # Auto-clean mode (tu Task Scheduler)
    if "--auto-clean" in sys.argv:
        log("=== AUTO-CLEAN TRIGGERED BY SCHEDULER ===")
        s       = load_settings()
        t0      = time.time()
        si      = get_full_sysinfo()
        results = full_cleaner_parallel(s)
        duration = round(time.time() - t0, 1)
        generate_html_report_v4(results, si, duration, "Auto Clean")
        log(f"=== AUTO-CLEAN DONE in {duration}s ===")
        return 0

    # Context menu "Clean Here" mode
    if "--clean-path" in sys.argv:
        idx = sys.argv.index("--clean-path")
        if idx + 1 < len(sys.argv):
            path = sys.argv[idx + 1]
            ensure_admin()
            ensure_dirs()
            clean_path_mode(path)
        return 0

    # Force CLI
    if "--cli" in sys.argv or not TK_OK:
        startup_banner()
        cli_menu()
        return 0

    # GUI mode
    app = App()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())