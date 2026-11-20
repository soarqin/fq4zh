import argparse
import ctypes as ct
import json
import struct
import subprocess
import time
from ctypes import wintypes as wt
from pathlib import Path

from PIL import ImageGrab

from catalog import ROOT, WORK


USER = ct.windll.user32
KERNEL = ct.windll.kernel32
KERNEL.OpenProcess.restype = wt.HANDLE
USER.GetForegroundWindow.restype = wt.HWND
USER.WindowFromPoint.restype = wt.HWND
USER.GetAncestor.restype = wt.HWND
USER.SetProcessDPIAware()
ENUM = ct.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


def caption(window):
    value = ct.create_unicode_buffer(512)
    USER.GetWindowTextW(window, value, len(value))
    return value.value


def windows(pid):
    visible = []

    @ENUM
    def visit(window, _):
        owner = wt.DWORD()
        USER.GetWindowThreadProcessId(window, ct.byref(owner))
        if owner.value == pid and USER.IsWindowVisible(window):
            visible.append(window)
        return True

    USER.EnumWindows(visit, 0)
    return visible


def await_value(query, timeout=12):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        value = query()
        if value:
            return value
        time.sleep(0.06)
    raise RuntimeError('Timed out waiting for a game screen')


def foreground(window):
    USER.BringWindowToTop(window)
    USER.SetForegroundWindow(window)
    await_value(lambda: USER.GetForegroundWindow() == window, 2)


def geometry(window, client):
    rect = wt.RECT()
    if client:
        origin = wt.POINT()
        USER.GetClientRect(window, ct.byref(rect))
        USER.ClientToScreen(window, ct.byref(origin))
        return (origin.x, origin.y, origin.x + rect.right, origin.y + rect.bottom)
    USER.GetWindowRect(window, ct.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def snapshot(window, path, *, client=True):
    left, top, right, bottom = geometry(window, client)
    assert right > left and bottom > top
    for x, y in ((left+3, top+3), (right-4, top+3), (left+3, bottom-4), (right-4, bottom-4),
                 ((left+right)//2, (top+bottom)//2)):
        hit = USER.WindowFromPoint(wt.POINT(x, y))
        if USER.GetAncestor(hit, 2) != window:
            raise RuntimeError('Another window covers the game')
    ImageGrab.grab(bbox=(left, top, right, bottom), all_screens=True).save(path)


def click(window, x, y, *, right=False):
    left, top, x2, y2 = geometry(window, True)
    assert USER.GetForegroundWindow() == window
    assert 0 <= x < x2-left and 0 <= y < y2-top
    assert USER.GetAncestor(USER.WindowFromPoint(wt.POINT(left+x, top+y)), 2) == window
    USER.SetCursorPos(left+x, top+y)
    time.sleep(0.075)
    down, up = (8, 16) if right else (2, 4)
    USER.mouse_event(down, 0, 0, 0, 0)
    time.sleep(0.10)
    USER.mouse_event(up, 0, 0, 0, 0)


def start_windowed(dialog, sound=0):
    sound_button = 1002 + sound
    for ident in (1001, sound_button):
        USER.SendMessageW(dialog, 0x111, ident, USER.GetDlgItem(dialog, ident))
    for ident, value in ((1000, 0), (1001, 1)):
        USER.SendMessageW(USER.GetDlgItem(dialog, ident), 0xF1, value, 0)
    for ident in (1002, 1003, 1004):
        USER.SendMessageW(USER.GetDlgItem(dialog, ident), 0xF1, ident == sound_button, 0)
    combo = USER.GetDlgItem(dialog, 1007)
    USER.SendMessageW(combo, 0x14E, 0, 0)
    USER.PostMessageW(dialog, 0x111, 1, USER.GetDlgItem(dialog, 1))


def verify(exe, output, difficulty, opening_seconds, sound, *, launch=subprocess.Popen, require_zero_exit=True):
    output.mkdir(parents=True, exist_ok=True)
    previous = USER.GetForegroundWindow()
    cursor = wt.POINT()
    USER.GetCursorPos(ct.byref(cursor))
    process = launch([str(exe)], cwd=exe.parent)
    handle = KERNEL.OpenProcess(0x10, False, process.pid)
    report = {}

    def read(addr, count):
        buffer = ct.create_string_buffer(count)
        if not KERNEL.ReadProcessMemory(wt.HANDLE(handle), ct.c_void_p(addr), buffer, count, None):
            raise RuntimeError(f'Cannot read test instance memory at {addr:x}')
        return buffer.raw

    def number(addr):
        return struct.unpack('<I', read(addr, 4))[0]

    def menu_at(address):
        return address in struct.unpack('<8I', read(0x5583A4, 32))

    try:
        dialog = await_value(lambda: next((h for h in windows(process.pid) if caption(h) == 'FQ4 啟動選單'), None))
        foreground(dialog)
        time.sleep(0.25)
        snapshot(dialog, output / 'startup.png', client=False)
        report['startup'] = caption(dialog)
        start_windowed(dialog, sound)
        main = await_value(lambda: next((h for h in windows(process.pid) if caption(h).startswith('FirstQueen4')), None))
        foreground(main)

        for _ in range(40):
            # The active title menu owns the first text-window pointer.
            if menu_at(0x4A93D8):
                break
            click(main, 300, 200)
            time.sleep(0.25)
        else:
            raise RuntimeError('Title menu did not start')
        snapshot(main, output / 'title.png')
        click(main, 386, 344)
        await_value(lambda: menu_at(0x4A946C))
        time.sleep(0.25)
        snapshot(main, output / 'load-menu.png')
        report['load_menu_seen'] = True
        assert USER.GetForegroundWindow() == main
        USER.keybd_event(0x1B, 0, 0, 0)  # Escape leaves the save list.
        time.sleep(0.10)
        USER.keybd_event(0x1B, 0, 2, 0)
        await_value(lambda: menu_at(0x4A93D8))
        click(main, 386, 328)
        await_value(lambda: menu_at(0x4A93F4))
        time.sleep(0.25)
        snapshot(main, output / 'difficulty.png')
        click(main, 420, 329 + 16 * difficulty)

        await_value(lambda: read(0x57A7E4, 1) != b'\0')
        seen = set()
        glyphs = set()
        until = time.monotonic() + opening_seconds
        while time.monotonic() < until:
            current = read(0x57A7E4, 768).split(b'\0', 1)[0]
            if current and current not in seen:
                seen.add(current)
                if len(seen) <= 4:
                    snapshot(main, output / f'story-{len(seen)}.png')
                count = min(int.from_bytes(read(0x58D2A8, 2), 'little'), 2048)
                if count:
                    sprites = read(0x4C6EC8, count * 40)
                    for sprite in range(0, len(sprites), 40):
                        if sprites[sprite+38:sprite+40] == b'\x0a\0':
                            char = int.from_bytes(sprites[sprite+12:sprite+14], 'little')
                            if 0x4E00 <= char <= 0x9FFF:
                                glyphs.add(chr(char))
            if number(0x5E903C) == 403:
                break
            click(main, 350, 270)
            time.sleep(0.13)
        report['difficulty_row'] = difficulty
        report['story_buffers_seen'] = len(seen)
        report['cjk_glyphs_in_sprites'] = ''.join(sorted(glyphs))
        assert len(seen) >= 3, 'Did not advance through opening dialogue'
        report['sound_mode'] = number(0x4BAA2C)
        report['plain_sound_enabled'] = bool(number(0x5BDF48))
        report['directmusic_enabled'] = bool(number(0x4BA71C))
        assert report['sound_mode'] == sound
        assert report['plain_sound_enabled'] == (sound == 1)
        assert report['directmusic_enabled'] == (sound == 2)
        report['world_map_reached'] = number(0x5E903C) == 403
        snapshot(main, output / 'game.png')

        USER.PostMessageW(main, 0x112, 0xF060, 0)  # The window's Close command.
        close = await_value(lambda: next((h for h in windows(process.pid) if h != main), None))
        labels = []

        @ENUM
        def child(h, _):
            labels.append(caption(h))
            return True

        USER.EnumChildWindows(close, child, 0)
        assert '要結束遊戲嗎？' in labels, labels
        report['exit_confirmation'] = '要結束遊戲嗎？'
        USER.PostMessageW(close, 0x111, 6, USER.GetDlgItem(close, 6))
        process.wait(timeout=8)
        report['exit_code'] = process.returncode
        if require_zero_exit:
            assert process.returncode == 0
    finally:
        KERNEL.CloseHandle(wt.HANDLE(handle))
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        USER.SetCursorPos(cursor.x, cursor.y)
        if previous and USER.IsWindow(previous):
            USER.SetForegroundWindow(previous)
        (output / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Play the opening of a local build in a window and check the text paths.')
    parser.add_argument('--exe', type=Path, default=ROOT / 'dist' / 'FQ4' / 'fq4.exe')
    parser.add_argument('--out', type=Path, default=WORK / 'smoke')
    parser.add_argument('--difficulty', type=int, choices=range(5), default=0)
    parser.add_argument('--opening-seconds', type=int, default=95)
    parser.add_argument('--sound', type=int, choices=(0, 1, 2), default=0,
                        help='Startup sound selection, zero-based')
    args = parser.parse_args()
    verify(args.exe.resolve(), args.out, args.difficulty, args.opening_seconds, args.sound)
