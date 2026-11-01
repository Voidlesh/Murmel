"""Foreground-app detection and pasting text into the focused window."""
from __future__ import annotations

import ctypes
import logging
import threading
import time
from ctypes import wintypes

import comtypes
import comtypes.client
import keyboard
import psutil

log = logging.getLogger(__name__)

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
CLIPBOARD_RETRIES = 10
RESTORE_DELAY_S = 0.6

user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.GetClipboardData.restype = wintypes.HANDLE
user32.GetClipboardData.argtypes = [wintypes.UINT]
user32.SetClipboardData.restype = wintypes.HANDLE
user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalLock.restype = wintypes.LPVOID
kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]


def foreground_app() -> tuple[str, str]:
    """Return (process name, window title) of the focused window."""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return "", ""
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    title = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, title, 512)
    try:
        name = psutil.Process(pid.value).name()
    except (psutil.Error, ValueError):
        name = ""
    return name, title.value


def categorize(app: str, title: str, style_apps: dict[str, list[str]]) -> str:
    """Map the target window to a style category. Title keywords (e.g. 'Gmail'
    in a browser) win over process names so web apps are recognised."""
    app_l, title_l = app.lower(), title.lower()
    for category, needles in style_apps.items():
        for needle in needles:
            n = needle.lower()
            if not n.endswith(".exe") and n and n in title_l:
                return category
    for category, needles in style_apps.items():
        if app_l and app_l in (n.lower() for n in needles):
            return category
    return "other"


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("hwndActive", wintypes.HWND),
        ("hwndFocus", wintypes.HWND),
        ("hwndCapture", wintypes.HWND),
        ("hwndMenuOwner", wintypes.HWND),
        ("hwndMoveSize", wintypes.HWND),
        ("hwndCaret", wintypes.HWND),
        ("rcCaret", wintypes.RECT),
    ]


user32.GetGUIThreadInfo.argtypes = [wintypes.DWORD, ctypes.POINTER(GUITHREADINFO)]


def has_text_caret() -> bool:
    """True when the focused window shows a text caret. Classic Win32 edit controls
    expose one; Chromium/Electron apps often do not, so a False here is not proof
    that no text field is focused."""
    info = GUITHREADINFO()
    info.cbSize = ctypes.sizeof(GUITHREADINFO)
    if not user32.GetGUIThreadInfo(0, ctypes.byref(info)):
        return True  # cannot tell, keep the normal paste path
    return bool(info.hwndCaret)


UIA_CLSID = "{ff48dba4-60ef-4201-aa87-54103eef594e}"
UIA_EDIT_CONTROL_TYPE = 50004


def _uia_focus_is_edit() -> bool:
    comtypes.CoInitialize()
    try:
        core = comtypes.client.GetModule("UIAutomationCore.dll")
        automation = comtypes.client.CreateObject(UIA_CLSID, interface=core.IUIAutomation)
        return automation.GetFocusedElement().CurrentControlType == UIA_EDIT_CONTROL_TYPE
    except comtypes.COMError:
        return False
    finally:
        comtypes.CoUninitialize()


def focused_text_input() -> bool:
    """True when the focused control takes typed text. Electron/Chromium apps (Claude, Slack,
    Discord) show no caret, so UI Automation decides there. They expose their fields only after
    the first query, so the engine also asks at recording start to warm them up."""
    return has_text_caret() or _uia_focus_is_edit()


def _open_clipboard() -> bool:
    for _ in range(CLIPBOARD_RETRIES):
        if user32.OpenClipboard(None):
            return True
        time.sleep(0.02)
    return False


def get_clipboard_text() -> str | None:
    if not user32.IsClipboardFormatAvailable(CF_UNICODETEXT) or not _open_clipboard():
        return None
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        ptr = kernel32.GlobalLock(handle)
        try:
            return ctypes.wstring_at(ptr)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def set_clipboard_text(text: str) -> None:
    data = ctypes.create_unicode_buffer(text)
    size = ctypes.sizeof(data)
    if not _open_clipboard():
        raise OSError("Zwischenablage ist gesperrt")
    try:
        user32.EmptyClipboard()
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
        ptr = kernel32.GlobalLock(handle)
        ctypes.memmove(ptr, data, size)
        kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            raise OSError(f"SetClipboardData fehlgeschlagen ({ctypes.get_last_error()})")
    finally:
        user32.CloseClipboard()


def paste_text(text: str, restore_clipboard: bool) -> None:
    previous = get_clipboard_text() if restore_clipboard else None
    set_clipboard_text(text)
    time.sleep(0.03)
    keyboard.send("ctrl+v")
    if previous is not None:
        threading.Timer(RESTORE_DELAY_S, _restore, args=(previous,)).start()


def _restore(previous: str) -> None:
    try:
        set_clipboard_text(previous)
    except OSError:
        log.warning("Zwischenablage konnte nicht wiederhergestellt werden")
