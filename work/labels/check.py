import argparse
import hashlib
import json
import struct
import subprocess
import sys
import time
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from smoke import KERNEL, USER, await_value, caption, click, ct, foreground, snapshot, start_windowed, wt, windows


def focus_game(window):
    try:
        foreground(window)
        return
    except RuntimeError:
        pass
    active = USER.GetForegroundWindow()
    if active:
        current = KERNEL.GetCurrentThreadId()
        owner = USER.GetWindowThreadProcessId(active, None)
        message = wt.MSG()
        USER.PeekMessageW(ct.byref(message), 0, 0, 0, 0)
        if USER.AttachThreadInput(current, owner, True):
            try:
                USER.BringWindowToTop(window)
                USER.SetForegroundWindow(window)
            finally:
                USER.AttachThreadInput(current, owner, False)
    await_value(lambda: USER.GetForegroundWindow() == window, 2)


def check(exe, output, party, sound, *, verify_interior=None, launch=subprocess.Popen):
    output.mkdir(parents=True, exist_ok=True)
    save = exe.with_name('save00.dat')
    save_digest = hashlib.sha256(save.read_bytes()).hexdigest()
    previous = USER.GetForegroundWindow()
    cursor = wt.POINT()
    USER.GetCursorPos(ct.byref(cursor))
    game = launch([str(exe)], cwd=exe.parent)
    handle = KERNEL.OpenProcess(0x10, False, game.pid)
    result = {'save_sha256': save_digest, 'party': party}

    def read(address, count):
        buffer = ct.create_string_buffer(count)
        if not KERNEL.ReadProcessMemory(wt.HANDLE(handle), ct.c_void_p(address), buffer, count, None):
            raise RuntimeError(f'Cannot read the test instance at {address:x}')
        return buffer.raw

    def number(address):
        return struct.unpack('<I', read(address, 4))[0]

    def menu_at(address):
        return address in struct.unpack('<8I', read(0x5583A4, 32))

    try:
        dialog = await_value(lambda: next((w for w in windows(game.pid) if caption(w).startswith('FQ4')), None))
        for slider in (1005, 1006):
            USER.SendMessageW(USER.GetDlgItem(dialog, slider), 0x405, 1, 3)
        start_windowed(dialog, sound)
        main = await_value(lambda: next((w for w in windows(game.pid) if caption(w).startswith('FirstQueen4')), None))
        focus_game(main)
        for _ in range(60):
            if menu_at(0x4A93D8):
                break
            click(main, 300, 200)
            time.sleep(0.24)
        else:
            raise RuntimeError('Title menu not reached')
        click(main, 386, 344)
        await_value(lambda: menu_at(0x4A946C))
        time.sleep(0.22)
        snapshot(main, output / 'load.png')
        click(main, 389, 344)
        await_value(lambda: number(0x5E903C) == 403)
        time.sleep(0.6)
        snapshot(main, output / 'map.png')
        click(main, 62, 64)
        selection = number(0x498040)
        await_value(lambda: menu_at(selection) or number(0x5E903C) == 404)
        if menu_at(selection):
            time.sleep(0.3)
            snapshot(main, output / 'explore.png')
            click(main, 70, 32 + 16 * party)
        await_value(lambda: number(0x5E903C) == 404)
        time.sleep(0.6)
        snapshot(main, output / 'label.png')
        result['map_interior'] = True
        result['sound_mode'] = number(0x4BAA2C)
        result['directmusic_enabled'] = bool(number(0x4BA71C))
        title_name = number(0x57C320)
        result['label_bytes'] = read(title_name, 10).hex()
        count = min(int.from_bytes(read(0x53E672, 2), 'little'), 8192)
        sprites = read(0x4C6EC8, count * 40)
        result['label_sprites'] = []
        for off in range(0, len(sprites), 40):
            _, x, y, width, height, cell, tile_x, tile_y = struct.unpack_from('<IhhhhHBB', sprites, off)
            kind = struct.unpack_from('<H', sprites, off + 38)[0]
            if 44 <= x < 128 and 0 <= y <= 4 and kind in (2, 10):
                result['label_sprites'].append(dict(x=x, y=y, width=width, height=height,
                    cell=f'{cell:04x}', tile_x=tile_x, tile_y=tile_y, type=kind))
        if verify_interior is not None:
            verify_interior(main, read, output, result)
        USER.PostMessageW(main, 0x112, 0xF060, 0)
        modal = await_value(lambda: next((w for w in windows(game.pid) if w != main), None))
        USER.PostMessageW(modal, 0x111, 6, USER.GetDlgItem(modal, 6))
        game.wait(timeout=6)
        result['exit_code'] = game.returncode
    finally:
        KERNEL.CloseHandle(wt.HANDLE(handle))
        if game.poll() is None:
            game.terminate()
            game.wait(timeout=5)
        USER.SetCursorPos(cursor.x, cursor.y)
        if previous and USER.IsWindow(previous):
            USER.SetForegroundWindow(previous)
        result['save_matches'] = hashlib.sha256(save.read_bytes()).hexdigest() == save_digest
        (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(result))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('exe', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--party', type=int, choices=(1, 2), default=1)
    parser.add_argument('--sound', type=int, choices=(0, 1, 2), default=0)
    args = parser.parse_args()
    check(args.exe.resolve(), args.output.resolve(), args.party, args.sound)
