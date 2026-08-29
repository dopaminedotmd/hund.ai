"""Clipboard integration for hund.ui.

Provides direct Win32 ctypes clipboard read/write on Windows without spawning
processes or flashing console windows, with cross-platform fallbacks for macOS
and Linux.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys


def _setup_win32_ctypes(user32, kernel32) -> None:
    import ctypes
    from ctypes import wintypes

    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.argtypes = []
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = wintypes.HANDLE
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE

    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.restype = wintypes.HGLOBAL


def _win32_copy(text: str) -> bool:
    """Copy text to Windows clipboard using ctypes user32/kernel32."""
    try:
        import ctypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        _setup_win32_ctypes(user32, kernel32)

        GMEM_MOVEABLE = 0x0002
        CF_UNICODETEXT = 13

        if not user32.OpenClipboard(None):
            return False

        try:
            user32.EmptyClipboard()
            encoded = text.encode("utf-16-le") + b"\x00\x00"
            size = len(encoded)

            h_global = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
            if not h_global:
                return False

            lp_global = kernel32.GlobalLock(h_global)
            if not lp_global:
                kernel32.GlobalFree(h_global)
                return False

            ctypes.memmove(lp_global, encoded, size)
            kernel32.GlobalUnlock(h_global)

            if not user32.SetClipboardData(CF_UNICODETEXT, h_global):
                kernel32.GlobalFree(h_global)
                return False
            return True
        finally:
            user32.CloseClipboard()
    except Exception:
        return False


def _win32_paste() -> str:
    """Read text from Windows clipboard using ctypes user32/kernel32."""
    try:
        import ctypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        _setup_win32_ctypes(user32, kernel32)

        CF_UNICODETEXT = 13

        if not user32.OpenClipboard(None):
            return ""

        try:
            h_data = user32.GetClipboardData(CF_UNICODETEXT)
            if not h_data:
                return ""

            lp_data = kernel32.GlobalLock(h_data)
            if not lp_data:
                return ""

            try:
                raw_text = ctypes.wstring_at(lp_data)
                return raw_text or ""
            finally:
                kernel32.GlobalUnlock(h_data)
        finally:
            user32.CloseClipboard()
    except Exception:
        return ""


def copy_text(text: str) -> bool:
    """Copy text to the system clipboard."""
    if not text:
        return False

    if sys.platform == "win32":
        if _win32_copy(text):
            return True
        # Fallback to clip command if ctypes fails
        try:
            subprocess.run(["clip"], input=text.encode("utf-8"), check=True, capture_output=True)
            return True
        except Exception:
            return False

    elif sys.platform == "darwin":
        if shutil.which("pbcopy"):
            try:
                subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True, capture_output=True)
                return True
            except Exception:
                pass

    else:
        # Linux / BSD: wl-copy, xclip, xsel
        for cmd in (["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]):
            if shutil.which(cmd[0]):
                try:
                    subprocess.run(cmd, input=text.encode("utf-8"), check=True, capture_output=True)
                    return True
                except Exception:
                    continue

    return False


def paste_text() -> str:
    """Retrieve text from the system clipboard."""
    if sys.platform == "win32":
        val = _win32_paste()
        if val:
            return val
        # Fallback to powershell Get-Clipboard if ctypes returned empty
        try:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
                capture_output=True,
                text=True,
                check=True,
                timeout=1.5,
            )
            return res.stdout.rstrip("\r\n")
        except Exception:
            return ""

    elif sys.platform == "darwin":
        if shutil.which("pbpaste"):
            try:
                res = subprocess.run(["pbpaste"], capture_output=True, text=True, check=True)
                return res.stdout
            except Exception:
                pass

    else:
        # Linux / BSD: wl-paste, xclip, xsel
        for cmd in (["wl-paste", "--no-newline"], ["xclip", "-selection", "clipboard", "-o"], ["xsel", "--clipboard", "--output"]):
            if shutil.which(cmd[0]):
                try:
                    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
                    return res.stdout
                except Exception:
                    continue

    return ""
