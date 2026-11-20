import argparse
import csv
import hashlib
import json
import re
import struct
import unicodedata
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'work'
WIN = Path(r'D:\Games\FQ4')
DOS = Path(r'D:\DOS\FQ4')
EXE_SHA256 = 'a58d24b16c5ce928ddf796b6470c0b2ea0e04fdc344e590ea9253bef48fad0fd'
DOS_SHA256 = {
    'FQ4MES': '8f8624d1b366a8556bac3ed22ffe0ec3c242d17537aac10d2dc8571138b315cc',
    'MAIN.EXE': 'e6aa90bfba9af64ca0837ae0230bc4b83b92b31d33e611702935b32ef540c18e',
}
STORY = 0x986D8
SLOTS = 800

# File offsets in Win v1.10 and the DOS MAIN.EXE distributed with this copy.
TABLES = {
    'person': (0xB46B8, 658, 10, 0x2EB9A, 0x3013D),
    'class': (0xB606C, 220, 9, 0x3013D, 0x308F9),
    'nation': (0xB791C, 17, 13, 0x30945, 0x30A22),
    'place': (0xB7B9D, 100, 17, 0x30A44, 0x310E8),
    'item': (0xB2020, 73, 17, 0x310E8, 0x31333),
    'effect': (0xB2590, 73, 27, 0x314E9, 0x318B8),
    'effect_hard': (0xB2D44, 73, 27, 0x314E9, 0x318B8),
    'spell': (0xB8784, 44, 11, 0x31A34, 0x31BF7),
    'spell_short': (0xB8968, 44, 9, 0x31A34, 0x31BF7),
}


def original_exe(folder):
    data = (folder / 'fq4.exe').read_bytes()
    if hashlib.sha256(data).hexdigest() != EXE_SHA256:
        raise ValueError('fq4.exe is not the verified Windows v1.10 build')
    return data


def dos_data(folder, name):
    data = (folder / name).read_bytes()
    if hashlib.sha256(data).hexdigest() != DOS_SHA256[name]:
        raise ValueError(f'{name} is not the verified Traditional Chinese DOS file')
    return data


def cstring(data, offset):
    if offset == len(data):
        return b''
    return data[offset:data.index(0, offset)]


def story_rows(win, dos):
    windows = struct.unpack_from(f'<{SLOTS}H', win, STORY)
    chinese = struct.unpack_from(f'<{SLOTS}H', dos)
    assert windows[:3] == (0x640, 0x640, 0x654)
    assert chinese[:3] == (0x640, 0x640, 0x65B)
    assert max(chinese) == len(dos)
    for index, (a, b) in enumerate(zip(windows, chinese)):
        jp = cstring(win, STORY + a).decode('cp932')
        raw = cstring(dos, b)
        yield dict(id=index, win=STORY+a, dos=b, ja=jp,
                   zh=raw.decode('cp950', 'backslashreplace'),
                   dos_hex=raw.hex() if index == 18 else '')


def table_rows(win, dos):
    for kind, (start, count, stride, dos_start, dos_end) in TABLES.items():
        slots = dos[dos_start:dos_end].split(b'\0')
        assert slots.pop() == b'', (kind, hex(dos_end))
        offset = dos_start
        for index in range(count):
            address = start + stride * index
            raw = win[address:address+stride]
            assert raw[-1] == 0 and b'\0' not in raw[:-1], (kind, index)
            ja = raw[:-1].decode('cp932').strip()
            slot = slots[index] if index < len(slots) else b''
            zh = slot.rstrip(b'\xfe').decode('cp950').strip()
            yield dict(kind=kind, id=index, win=address, stride=stride,
                       dos=offset if index < len(slots) else None,
                       ja=ja, normalized=unicodedata.normalize('NFKC', ja), zh=zh)
            offset += len(slot) + 1


def dos_ui(data):
    # Several DOS menus are bytecode. Each listed range contains literal text
    # operands or NUL-terminated prompts, with their source file offsets.
    for start, end in [(0x29400, 0x2A8C0), (0x2D000, 0x2DC60)]:
        run = re.compile(rb'(?:(?:[\xa1-\xf9][\x40-\x7e\xa1-\xfe])|[\x20-\x39])+')
        for match in run.finditer(data, start, end):
            try:
                s = match[0].decode('cp950').strip()
            except UnicodeDecodeError:
                continue
            if len(s) >= 2 and re.search(r'[\u4e00-\u9fff]{2}', s):
                yield dict(dos=match.start(), zh=s)


def win_ui(data):
    for start, end in [(0x98000, STORY), (0xA83A4, 0xACE30),
                       (0xB146C, 0xB14A0), (0xB99B8, 0xBAA25)]:
        for match in re.finditer(rb'[^\0]+', data[start:end]):
            raw = match[0]
            address = start + match.start()
            if raw.startswith(b'\xff\xff\xff\xff'):
                raw = raw[4:]
                address += 4
            try:
                value = raw.decode('cp932')
            except UnicodeDecodeError:
                continue
            if (re.search(r'[\u3040-\u30ff\u4e00-\u9fff]', value)
                and all(c.isprintable() or c in '\x01\x02\t\r\n\u3000' for c in value)
                and not re.search(r'[\ue000-\uf8ff]', value)):
                yield dict(win=address, bytes=len(raw), ja=value)


def save_tsv(path, rows):
    rows = list(rows)
    with path.open('w', encoding='utf-8', newline='') as file:
        writer = csv.DictWriter(file, rows[0].keys(), delimiter='\t')
        writer.writeheader()
        for row in rows:
            writer.writerow({k: (f'0x{v:x}' if k in ('win', 'dos') and v is not None
                                 else re.sub(r'[\x00-\x1f]', lambda m: f'\\x{ord(m[0]):02x}', v)
                                 if isinstance(v, str) else v) for k, v in row.items()})


def extract(windows, dos, output):
    win = original_exe(windows)
    main = dos_data(dos, 'MAIN.EXE')
    output.mkdir(parents=True, exist_ok=True)
    dialogue = list(story_rows(win, dos_data(dos, 'FQ4MES')))
    terms = list(table_rows(win, main))
    save_tsv(output / 'dialogue.tsv', dialogue)
    save_tsv(output / 'tables.tsv', terms)
    save_tsv(output / 'dos-ui.tsv', dos_ui(main))
    save_tsv(output / 'win-ui.tsv', win_ui(win))
    (output / 'source.json').write_text(json.dumps(dict(dialogue=dialogue, tables=terms),
                                                   ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'{len(dialogue)} dialogue slots, {len(terms)} table rows')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Extract the Japanese and official Traditional Chinese text.')
    parser.add_argument('--win', type=Path, default=WIN)
    parser.add_argument('--dos', type=Path, default=DOS)
    parser.add_argument('--out', type=Path, default=WORK / 'catalog')
    args = parser.parse_args()
    extract(args.win, args.dos, args.out)
