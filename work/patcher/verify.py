import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pefile
import psutil

WORK = Path(__file__).resolve().parent
ROOT = WORK.parents[1]
sys.path.insert(0, str(WORK.parent / 'labels'))
from check import check, focus_game
import smoke
from smoke import ENUM, USER, await_value, caption, ct, windows

SOURCE_CONTROL, BROWSE_BUTTON, WRITE_BUTTON, LAUNCH_BUTTON, STATUS_CONTROL = range(1001, 1006)
TOOL_TITLE = 'First Queen IV 中文补丁'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def result_at(directory):
    return json.loads((directory / 'result.json').read_text(encoding='utf-8'))


def map_caption(record):
    return ''.join(chr(int(sprite['cell'], 16)) for sprite in record['label_sprites']
                   if sprite['type'] == 10)


class GameProcess:
    def __init__(self, process):
        self.process = process
        self.pid = process.pid
        self.returncode = None

    def wait(self, timeout):
        self.returncode = self.process.wait(timeout=timeout)

    def poll(self):
        if self.returncode is None and not self.process.is_running():
            self.wait(0)
        return self.returncode

    def terminate(self):
        self.process.terminate()


def verify(candidate):
    stock = Path(r'D:\Games\FQ4')
    fixture = Path(tempfile.mkdtemp(prefix='verify-', dir=WORK))
    game_dir = fixture / 'Game copy'
    portable = fixture / 'Portable tool'
    output = WORK / 'verification'
    game_dir.mkdir()
    portable.mkdir()
    output.mkdir(exist_ok=True)
    for folder in ('DATA', 'PSDATA', 'BGM', 'FQ4HELP'):
        shutil.copytree(stock / folder, game_dir / folder)
    source = game_dir / 'fq4.exe'
    shutil.copy2(stock / source.name, source)
    save = game_dir / 'save00.dat'
    shutil.copy2(ROOT / 'dist/FQ4/save00.dat', save)
    chinese = game_dir / 'fq4.zh.exe'
    tool_exe = portable / candidate.name
    shutil.copy2(candidate, tool_exe)
    assert list(portable.iterdir()) == [tool_exe]

    original_hash = digest(source)
    save_hash = digest(save)
    original_mtime = source.stat().st_mtime_ns
    metadata = json.loads((WORK / 'payload.json').read_text(encoding='utf-8'))
    assert original_hash == metadata['source_sha256']
    dlls = {entry.dll.decode('ascii').upper() for entry in pefile.PE(str(tool_exe)).DIRECTORY_ENTRY_IMPORT}
    assert dlls <= {'KERNEL32.DLL', 'USER32.DLL', 'COMDLG32.DLL', 'BCRYPT.DLL'}, dlls

    patcher = subprocess.Popen([str(tool_exe)], cwd=portable)
    parent = psutil.Process(patcher.pid)
    started = []
    report = {'fixture': str(fixture), 'tool_sha256': digest(tool_exe), 'imports': sorted(dlls)}
    previous_focus = USER.GetForegroundWindow()

    def post(window, command):
        assert USER.PostMessageW(window, 0x111, command, USER.GetDlgItem(window, command))

    def errors():
        return next((w for w in windows(patcher.pid) if w != dialog), None)

    def popup_text(window):
        labels = []

        @ENUM
        def add(control, _):
            labels.append(caption(control))
            return True

        USER.EnumChildWindows(window, add, 0)
        return ' '.join(labels)

    def selected_path():
        value = ct.create_unicode_buffer(32768)
        USER.SendMessageW(USER.GetDlgItem(dialog, SOURCE_CONTROL), 0x0D, len(value), value)
        return value.value

    def select(path):
        edit = USER.GetDlgItem(dialog, SOURCE_CONTROL)
        assert USER.SendMessageW(edit, 0x0C, 0, ct.c_wchar_p(str(path)))
        assert selected_path() == str(path)

    def browse_source():
        post(dialog, BROWSE_BUTTON)
        chooser = await_value(errors)
        assert caption(chooser) == '选择日文版 First Queen IV'
        fields = []

        @ENUM
        def filename_field(control, _):
            name = ct.create_unicode_buffer(16)
            USER.GetClassNameW(control, name, len(name))
            if name.value == 'Edit' and USER.GetDlgCtrlID(control) == 1148:
                fields.append(control)
            return True

        USER.EnumChildWindows(chooser, filename_field, 0)
        assert len(fields) == 1
        assert USER.SendMessageW(fields[0], 0x0C, 0, ct.c_wchar_p(str(source)))
        post(chooser, 1)
        await_value(lambda: selected_path() == str(source))

    def reject(button, expected):
        post(dialog, button)
        error = await_value(errors)
        assert expected in await_value(lambda: popup_text(error).strip()), popup_text(error)
        assert USER.PostMessageW(error, 0x10, 0, 0)
        await_value(lambda: not errors())

    def launch_from_tool(command, cwd):
        assert Path(command[0]) == source and cwd == game_dir
        assert not parent.children()
        select(source)
        post(dialog, LAUNCH_BUTTON)

        def find_child():
            error = errors()
            if error:
                raise RuntimeError(f'Memory mode displayed an error dialog. {popup_text(error)}')
            if '中文版已启动' not in caption(USER.GetDlgItem(dialog, STATUS_CONTROL)):
                return None
            return next(iter(parent.children()), None)

        game = GameProcess(await_value(find_child))
        started.append(game)
        assert Path(game.process.exe()) == source
        report['memory_process_image'] = game.process.exe()
        report['memory_started_by_tool'] = game.process.ppid() == patcher.pid
        return game

    try:
        dialog = await_value(lambda: next((w for w in windows(patcher.pid) if caption(w) == TOOL_TITLE), None))
        assert caption(USER.GetDlgItem(dialog, WRITE_BUTTON)) == '生成中文版 EXE'
        browse_source()
        report['original_selected_through_file_chooser'] = True

        # A byte change at the same file size must be rejected in both modes.
        altered = game_dir / 'different.exe'
        changed = bytearray(source.read_bytes())
        changed[-1] ^= 1
        altered.write_bytes(changed)
        select(altered)
        reject(WRITE_BUTTON, 'v1.10 原始 EXE')
        reject(LAUNCH_BUTTON, 'v1.10 原始 EXE')
        assert not altered.with_suffix('.zh.exe').exists() and not parent.children()
        report['incorrect_source_rejected_in_both_modes'] = True

        smoke.foreground = focus_game
        smoke.verify(source, output / 'memory-opening', 0, 18, 2, launch=launch_from_tool,
                     require_zero_exit=False)
        opening = result_at(output / 'memory-opening')
        # The legacy WinMain can return a message's wParam after normal WM_QUIT cleanup.
        assert 0 <= opening['exit_code'] < 0x80000000
        audit_file = WORK.parent / 'render-audit' / 'check.py'
        spec = importlib.util.spec_from_file_location('render_audit_check', audit_file)
        render_audit = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(render_audit)
        check(source, output / 'memory-explore', 1, 2, launch=launch_from_tool,
              verify_interior=render_audit.verify_rows)
        memory = result_at(output / 'memory-explore')
        assert map_caption(memory) == '艾雷斯'
        assert 0 <= memory['exit_code'] < 0x80000000
        assert memory['directmusic_enabled'] and memory['save_matches']
        assert bytes.fromhex(memory['standby']['label_bytes']).decode('utf-16le') == '待命中\0'
        assert memory['status_row']['members'] == 13
        assert digest(source) == original_hash and source.stat().st_mtime_ns == original_mtime
        assert not chinese.exists()
        report['memory_original_exe_unchanged'] = True
        report['memory_chinese_file_created'] = False
        report['memory_map_caption'] = map_caption(memory)
        report['memory_exit_code'] = memory['exit_code']

        japanese = subprocess.Popen([str(source)], cwd=game_dir)
        try:
            original_menu = await_value(lambda: next((window for window in windows(japanese.pid)
                if caption(window) == 'FQ4 ～起動メニュー～'), None))
            report['startup_when_launched_without_tool'] = caption(original_menu)
            assert USER.PostMessageW(original_menu, 0x10, 0, 0)
            japanese.wait(timeout=5)
        finally:
            if japanese.poll() is None:
                japanese.terminate()
                japanese.wait(timeout=5)

        select(source)
        marker = b'Existing output to preserve'
        chinese.write_bytes(marker)
        reject(WRITE_BUTTON, '同目录已有 fq4.zh.exe')
        assert chinese.read_bytes() == marker
        chinese.unlink()
        report['existing_file_preserved'] = True

        file_status = USER.GetDlgItem(dialog, STATUS_CONTROL)
        for _ in range(2):
            USER.SendMessageW(file_status, 0x0C, 0, ct.c_wchar_p(''))
            post(dialog, WRITE_BUTTON)
            await_value(lambda: '已就绪。' in caption(file_status))
            assert digest(chinese) == metadata['target_sha256']
        assert not list(game_dir.glob(chinese.name + '.*.tmp'))

        check(chinese, output / 'disk-explore', 2, 1)
        disk = result_at(output / 'disk-explore')
        assert map_caption(disk) == '利斯萊姆'
        assert 0 <= disk['exit_code'] < 0x80000000 and disk['save_matches']
        assert digest(source) == original_hash and source.stat().st_mtime_ns == original_mtime
        assert digest(save) == save_hash
        assert digest(stock / source.name) == original_hash
        report['disk_original_exe_unchanged'] = True
        report['disk_chinese_sha256'] = digest(chinese)
        report['disk_map_caption'] = map_caption(disk)
        report['disk_exit_code'] = disk['exit_code']
        report['save_sha256'] = save_hash
        report['opening_dialogue_buffers'] = opening['story_buffers_seen']
        print(json.dumps(report, ensure_ascii=False))
    finally:
        for game in started:
            if game.poll() is None:
                game.terminate()
                game.wait(5)
        if patcher.poll() is None:
            if 'dialog' in locals() and USER.IsWindow(dialog):
                USER.PostMessageW(dialog, 0x10, 0, 0)
            try:
                patcher.wait(timeout=2)
            except subprocess.TimeoutExpired:
                patcher.terminate()
                patcher.wait(timeout=5)
        if previous_focus and USER.IsWindow(previous_focus):
            USER.SetForegroundWindow(previous_focus)
        (output / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    verify(Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else WORK / 'FQ4ChinesePatch.exe')
