import argparse
import json
import os
import struct
import subprocess
import sys
import time
from pathlib import Path

import pefile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from smoke import KERNEL, USER, ENUM, await_value, caption, click, ct, start_windowed, wt, windows


BREAKPOINTS = {
    0x441AC0: 'DirectSoundCreate',
    0x441BAC: 'Initialize plain sound buffers',
    0x442796: 'Create IDirectMusicPerformance8',
    0x4427D0: 'InitAudio',
    0x4427FC: 'GetDefaultAudioPath',
    0x442835: 'CreateStandardAudioPath BGM',
    0x442861: 'CreateStandardAudioPath SFX',
    0x4428C3: 'GetObjectInPath BGM',
    0x4428EF: 'GetObjectInPath SFX',
    0x442910: 'Create IDirectMusicLoader8',
    0x443333: 'PlaySegmentEx',
    0x443657: 'SetFX',
    0x44368D: 'GetObjectInPath Reverb',
    0x4436B5: 'SetPreset',
    0x4436CC: 'Activate audio path',
    0x4436E0: 'Show audio error',
}


def breakpoints(exe):
    addresses = BREAKPOINTS.copy()
    pe = pefile.PE(exe)
    hook = 0x443657
    raw = pe.get_data(hook - 0x400000, 5)
    if raw.startswith(b'\xe9'):
        entry = hook + 5 + struct.unpack_from('<i', raw, 1)[0]
        body = pe.get_data(entry - 0x400000, 144)
        for name, sequence in (
            ('Waves SetFX', 'ff525485c0'),
            ('Waves GetObjectInPath', 'ff525c85c0'),
            ('Waves SetAllParameters', 'ff520c50'),
        ):
            addresses[entry + body.index(bytes.fromhex(sequence)) + 3] = name
    return addresses


def run(exe, sound, report_path, trace, seconds):
    process = subprocess.Popen([str(exe)], cwd=exe.parent)
    previous = USER.GetForegroundWindow()
    cursor = wt.POINT()
    USER.GetCursorPos(ct.byref(cursor))
    handle = KERNEL.OpenProcess(0x10, False, process.pid)
    debugger = None
    report = {'exe': str(exe), 'selected': sound, 'errors': []}

    def read(address, count):
        value = ct.create_string_buffer(count)
        if not KERNEL.ReadProcessMemory(wt.HANDLE(handle), ct.c_void_p(address), value, count, None):
            raise RuntimeError(f'Could not read {address:#x}')
        return value.raw

    def number(address):
        return struct.unpack('<I', read(address, 4))[0]

    if trace:
        cmd = report_path.with_suffix('.cdb')
        cmd.write_text(''.join(
            f'bp {address:08x} ".printf \\"{name} eax=%08x esi=%08x ebx=%08x\\n\\", @eax, @esi, @ebx; gc"\n'
            for address, name in breakpoints(exe).items()
        ) + '.echo TRACE READY\ng\n', encoding='ascii')
        log = report_path.with_suffix('.log')
        debugger_path = Path(os.environ['ProgramFiles(x86)']) / 'Windows Kits/10/Debuggers/x86/cdb.exe'

    try:
        dialog = await_value(lambda: next((h for h in windows(process.pid) if caption(h).startswith('FQ4')), None))
        if trace:
            with log.open('wb', buffering=0) as output:
                debugger = subprocess.Popen(
                    [str(debugger_path), '-p', str(process.pid), '-G', '-y', str(Path(os.environ['WINDIR'])), '-cf', str(cmd)],
                    stdout=output, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            await_value(lambda: b'TRACE READY' in log.read_bytes() if log.is_file() else False)
        for slider in (1005, 1006):
            USER.SendMessageW(USER.GetDlgItem(dialog, slider), 0x405, 1, 3)
        start_windowed(dialog, sound)
        main = None
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline and process.poll() is None:
            if dialog in windows(process.pid):
                time.sleep(0.1)
                continue
            for window in windows(process.pid):
                title = caption(window)
                if title.startswith('FirstQueen4'):
                    main = window
                else:
                    lines = []

                    @ENUM
                    def visit(child, _):
                        lines.append(caption(child))
                        return True

                    USER.EnumChildWindows(window, visit, 0)
                    if lines and lines not in report['errors']:
                        report['errors'].append(lines)
                    USER.PostMessageW(window, 0x111, 1, USER.GetDlgItem(window, 1))
            if main and USER.IsWindowEnabled(main) and number(0x5E903C) >= 400:
                report['game_loop_reached'] = True
                if 0x4A93D8 in struct.unpack('<8I', read(0x5583A4, 32)):
                    report['title_reached'] = True
                    break
                if USER.GetForegroundWindow() == main:
                    click(main, 300, 200)
            time.sleep(0.15)
        report['mode'] = number(0x4BAA2C)
        report['plain_sound'] = number(0x5BDF48)
        report['effects'] = number(0x4BA71C)
        report['engine_state'] = number(0x5E903C)
        report['audio_paths'] = struct.unpack('<5I', read(0x5BDF5C, 20))
        report['effect_buffers'] = struct.unpack('<4I', read(0x5BDF4C, 16))
        if main:
            USER.PostMessageW(main, 0x10, 0, 0)
            process.wait(timeout=5)
        report['exit_code'] = process.returncode
    finally:
        if handle:
            KERNEL.CloseHandle(wt.HANDLE(handle))
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        if debugger:
            try:
                debugger.wait(timeout=5)
            except subprocess.TimeoutExpired:
                debugger.terminate()
                debugger.wait(timeout=5)
        USER.SetCursorPos(cursor.x, cursor.y)
        if previous and USER.IsWindow(previous):
            USER.SetForegroundWindow(previous)
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('exe', type=Path)
    parser.add_argument('sound', type=int, choices=(0, 1, 2))
    parser.add_argument('report', type=Path)
    parser.add_argument('--trace', action='store_true')
    parser.add_argument('--seconds', type=int, default=14)
    args = parser.parse_args()
    run(args.exe.resolve(), args.sound, args.report.resolve(), args.trace, args.seconds)
