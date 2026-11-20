import argparse
import struct
import sys
import time
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'labels'))
from check import USER, await_value, check, click, snapshot
from smoke import geometry


def key(window, code):
    assert USER.GetForegroundWindow() == window
    scan = USER.MapVirtualKeyW(code, 4)
    flags = int(code == 0x24 or scan >> 8 == 0xE0)
    USER.keybd_event(code, scan & 0xFF, flags, 0)
    time.sleep(0.32)
    USER.keybd_event(code, scan & 0xFF, flags | 2, 0)


def verify_rows(window, read, output, result):
    def menu_at(address):
        return address in struct.unpack('<8I', read(0x5583A4, 32))

    def leave(*addresses):
        for address in addresses:
            await_value(lambda: menu_at(address), 3)
            click(window, 86, 60, right=True)
            time.sleep(0.30)
            if menu_at(address):
                snapshot(window, output / f'menu-{address:x}.png')
                raise RuntimeError(f'Menu {address:x} did not close')

    party_menu = 0x4A860C
    system_menu = 0x4A8AB0
    side_menu = 0x4A8E64
    visibility_menu = 0x4A8EB8
    key(window, 0x24)  # Home opens the interior party menu.
    await_value(lambda: menu_at(party_menu), 3)
    snapshot(window, output / 'party-menu.png')
    click(window, 86, 144)  # 系統
    await_value(lambda: menu_at(system_menu), 3)
    click(window, 86, 64)  # 狀態顯示設定
    await_value(lambda: menu_at(side_menu), 3)
    click(window, 86, 64)  # 操控部隊設定
    await_value(lambda: menu_at(visibility_menu), 3)
    snapshot(window, output / 'visibility.png')
    name_row = 0x58D2AC + 4 * 5
    x, y = struct.unpack('<hh', read(name_row, 4))
    if x < 0:
        click(window, 86, 144)  # 姓名(NAME)
        await_value(lambda: struct.unpack('<h', read(name_row, 2))[0] >= 0, 3)
    leave(visibility_menu, side_menu, system_menu, party_menu)

    # Resize the in-game map window to expose the enabled status rows below it.
    pane_x, pane_y, pane_width, pane_height = struct.unpack('<4h', read(0x57C308, 8))
    left, top, right, bottom = geometry(window, True)
    corner_x, corner_y = pane_x + pane_width + 7, pane_y + pane_height + 7
    assert 0 <= corner_x < right - left and 0 <= corner_y < bottom - top
    assert USER.GetForegroundWindow() == window
    USER.SetCursorPos(left + corner_x, top + corner_y)
    time.sleep(0.10)
    USER.mouse_event(2, 0, 0, 0, 0)
    try:
        time.sleep(0.25)
        USER.SetCursorPos(left + corner_x, top + y - 30)
        time.sleep(0.40)
    finally:
        USER.mouse_event(4, 0, 0, 0, 0)
    await_value(lambda: struct.unpack('<h', read(0x57C30E, 2))[0] < pane_height, 3)
    time.sleep(0.25)
    snapshot(window, output / 'status.png')
    x, y = struct.unpack('<hh', read(name_row, 4))
    assert x >= 0 and y >= 0, (x, y)
    party_offset = struct.unpack('<H', read(0x529EDA, 2))[0]
    assert party_offset != 0xFFFF
    member_count = read(0x557F39 + party_offset, 1)[0]
    assert member_count
    member = struct.unpack('<H', read(0x557F48 + party_offset, 2))[0]
    name = struct.unpack('<I', read(0x52BDEC + 80 * member, 4))[0]
    result['status_row'] = dict(x=x, y=y, members=member_count,
                                first_member_bytes=read(name, 10).split(b'\0', 1)[0].hex())

    key(window, 0x24)
    await_value(lambda: menu_at(party_menu), 3)
    click(window, 86, 128)  # 視窗
    view_menu = 0x4A8A28
    await_value(lambda: menu_at(view_menu), 3)
    click(window, 86, 80)  # 敵軍視窗設定
    enemy_menu = 0x4A8BC4
    await_value(lambda: menu_at(enemy_menu), 3)
    click(window, 86, 80)  # 開啟
    time.sleep(0.30)
    leave(view_menu, party_menu)
    enemy_pane = struct.unpack('<I', read(0x52E628, 4))[0]
    flags, x, y, width, height = struct.unpack('<I4h', read(enemy_pane, 12))
    assert flags & 0x4000000 and not flags & 0x80000000, hex(flags)
    time.sleep(0.25)
    snapshot(window, output / 'standby.png')
    result['standby'] = dict(x=x, y=y, width=width, height=height, flags=hex(flags),
                             label_bytes=read(0x4B99F0, 8).hex())


if __name__ == '__main__':
    cli = argparse.ArgumentParser()
    cli.add_argument('exe', type=Path)
    cli.add_argument('output', type=Path)
    cli.add_argument('--party', type=int, choices=(1, 2), default=1)
    args = cli.parse_args()
    check(args.exe.resolve(), args.output.resolve(), args.party, 0, verify_interior=verify_rows)
