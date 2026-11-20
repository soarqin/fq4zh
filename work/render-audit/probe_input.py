import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'labels'))
from check import USER, check, click, snapshot


def probe(window, read, output, result):
    def state():
        return {hex(addr): read(addr, size).hex() for addr, size in (
            (0x55A3E4, 8), (0x52A2B8, 4), (0x529DC8, 4), (0x52BD30, 4),
            (0x5BE458, 42), (0x5583A4, 32), (0x58D2AC, 112), (0x5BE247, 1))}

    result['idle'] = state()
    for key, label in ((0x24, 'home'), (0x1B, 'escape'), (0x76, 'f7')):
        scan = USER.MapVirtualKeyW(key, 4)
        flags = int(scan >> 8 == 0xE0)
        assert USER.GetForegroundWindow() == window
        USER.keybd_event(key, scan & 0xFF, flags, 0)
        try:
            time.sleep(0.35)
            result[label] = state()
            snapshot(window, output / f'{label}.png')
        finally:
            USER.keybd_event(key, scan & 0xFF, flags | 2, 0)
        time.sleep(0.25)
    click(window, 13, 8, right=True)
    result['right-title'] = state()
    snapshot(window, output / 'right-title.png')


root = Path(__file__).resolve().parent
check(root / 'before/fq4.exe', root / 'probe', 1, 0, verify_interior=probe)
