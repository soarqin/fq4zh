import argparse
import collections
import re
import shutil
import struct
from pathlib import Path

import pefile

from catalog import ROOT, WORK, dos_data, dos_ui, original_exe, save_tsv, story_rows, table_rows, win_ui
from locale_text import localize_story, localize_table
from reverb import reverb_data
from runtime import BUFFER_SIZE, IMAGE_BASE, patch_runtime, u32


FULLWIDTH_SPACE = b'\x81\x40'


class Glyphs:
    def __init__(self):
        self.decode = [0x25A1] * 65536
        self.encode = {}
        spare = []
        for lead in (*range(0x81, 0xA0), *range(0xE0, 0xFD)):
            for trail in range(0x40, 0xFD):
                if trail == 0x7F:
                    continue
                pair = bytes([lead, trail])
                try:
                    value = pair.decode('cp932')
                except UnicodeDecodeError:
                    # Both the choice hit test and the legacy line parser accept these leads.
                    if lead < 0xF0:
                        spare.append(pair)
                    continue
                self.decode[int.from_bytes(pair, 'little')] = ord(value)
        self.spare = iter(spare)

    def cell(self, char):
        if char not in self.encode:
            try:
                raw = char.encode('cp932')
            except UnicodeEncodeError:
                raw = next(self.spare)
                self.decode[int.from_bytes(raw, 'little')] = ord(char)
            self.encode[char] = raw
        return self.encode[char]

    def cells(self, value):
        return b''.join(self.cell(c) for c in value)

    def encoder(self):
        lookup = [0] * 65536
        for c, b in self.encode.items():
            lookup[ord(c)] = int.from_bytes(b, 'little')
        return struct.pack('<65536H', *lookup)


def fit(raw, width, *, fullwidth):
    remaining = width - len(raw)
    if remaining < 0:
        raise ValueError(f'{len(raw)} bytes do not fit in {width}')
    if fullwidth and remaining % 2 == 0:
        return raw + FULLWIDTH_SPACE * (remaining // 2)
    return raw + b' ' * remaining


def patch_game_ui(pe, source, glyphs, rules):
    find = re.compile('|'.join(re.escape(s) for s in sorted(rules, key=len, reverse=True)))
    rows = []
    for row in win_ui(source):
        off, width, ja = (row[key] for key in ('win', 'bytes', 'ja'))
        if off >= 0xB99B8:
            continue
        pos = off
        for match in find.finditer(ja):
            start = off + len(ja[:match.start()].encode('cp932'))
            old = match[0].encode('cp932')
            target = rules[match[0]]
            try:
                new = fit(glyphs.cells(target), len(old), fullwidth=True)
            except ValueError as error:
                raise ValueError((hex(off), match[0], target, str(error))) from error
            pe.patch(IMAGE_BASE + start, old, new)
            pos = start + len(old)
        if pos != off:
            rows.append(dict(**row, target=find.sub(lambda m: rules[m[0]], ja), origin='ui-terms'))
    return rows


def patch_diagnostics(pe, source, glyphs, add, convert):
    rows = []
    for line in (ROOT / 'tools' / 'diagnostics.tsv').read_text(encoding='utf-8').splitlines():
        address, target = line.split('\t')
        offset = int(address, 16)
        target = convert(target.replace(r'\n', '\n'))
        raw = source[offset:source.index(0, offset)]
        japanese = raw.decode('cp932')
        placeholders = r'%[dxs]'
        assert re.findall(placeholders, target) == re.findall(placeholders, japanese), address
        if offset == 0xB99F0:
            # The standby panel calls DrawTextW directly. Its three-glyph
            # label has an extra alignment byte for the UTF-16 terminator.
            pe.patch(IMAGE_BASE + offset, raw + b'\0\0', (target + '\0').encode('utf-16le'))
        elif len(replacement := glyphs.cells(target) + b'\0') <= len(raw) + 1:
            pe.patch(IMAGE_BASE + offset, raw, replacement[:-1].ljust(len(raw), b'\0'))
        else:
            # Fixed references can be moved when the new text grows.
            original = u32(IMAGE_BASE + offset)
            refs = list(re.finditer(re.escape(b'\x68' + original), source[0x1000:0x8822E]))
            assert refs, address
            addr = add(replacement)
            for ref in refs:
                pe.patch(IMAGE_BASE + 0x1000 + ref.start() + 1, original, u32(addr))
        rows.append(dict(win=offset, bytes=len(raw), ja=japanese, target=target, origin='windows'))
    return rows


def align(value, alignment):
    return (value + alignment - 1) // alignment * alignment


class PE:
    def __init__(self, source):
        self.data = bytearray(source)
        self.pe = pefile.PE(data=source)
        hdr = self.pe.OPTIONAL_HEADER
        assert hdr.ImageBase == IMAGE_BASE
        self.next_rva = hdr.SizeOfImage
        self.section_alignment = hdr.SectionAlignment
        self.file_alignment = hdr.FileAlignment
        self.headers = self.pe.sections[-1].get_file_offset() + 40
        self.count = self.pe.FILE_HEADER.NumberOfSections

    def section(self, name, payload, characteristics):
        raw = align(len(self.data), self.file_alignment)
        length = align(len(payload), self.file_alignment)
        assert self.headers + 40 <= self.pe.sections[0].PointerToRawData
        struct.pack_into('<8s6I2HI', self.data, self.headers, name, len(payload), self.next_rva,
                         length, raw, 0, 0, 0, 0, characteristics)
        self.data.extend(b'\0' * (raw - len(self.data)))
        self.data.extend(payload)
        self.data.extend(b'\0' * (length - len(payload)))
        address = IMAGE_BASE + self.next_rva
        self.next_rva = align(self.next_rva + len(payload), self.section_alignment)
        self.headers += 40
        self.count += 1
        struct.pack_into('<H', self.data, self.pe.FILE_HEADER.get_field_absolute_offset('NumberOfSections'), self.count)
        struct.pack_into('<I', self.data, self.pe.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfImage'), self.next_rva)
        field = 'SizeOfCode' if characteristics & 0x20 else 'SizeOfInitializedData'
        pos = self.pe.OPTIONAL_HEADER.get_field_absolute_offset(field)
        length += struct.unpack_from('<I', self.data, pos)[0]
        struct.pack_into('<I', self.data, pos, length)
        return address

    def patch(self, va, expected, replacement):
        off = self.pe.get_offset_from_rva(va - IMAGE_BASE)
        assert len(expected) == len(replacement) and self.data[off:off+len(expected)] == expected, hex(va)
        self.data[off:off+len(expected)] = replacement


DIALOG_TEXT = {
    'FQ4 ～起動メニュー～': 'FQ4 啟動選單', '画面モード': '畫面模式',
    'フルスクリーンモード': '全螢幕模式', 'ウインドウモード': '視窗模式',
    'サウンド設定': '音效設定', 'サウンドなし': '關閉音效',
    'サウンドあり、エフェクトなし': '開啟音效，關閉音效特效',
    'サウンドあり、エフェクトあり': '開啟音效與音效特效',
    'ＢＧＭ音量': '背景音樂音量', '効果音音量': '效果音音量',
    'ゲーム内のウインドウを初期化する': '重設遊戲內視窗',
    'アルファブレンディングを使用しない': '停用透明混合',
    '開始': '開始', 'キャンセル': '取消',
}


def localize_dialog(raw, convert, font_name):
    style, _, controls = struct.unpack_from('<IIH', raw)
    result = bytearray(raw[:18])
    pos = 18
    seen = set()

    def variable(translate=False, font=False):
        nonlocal pos
        begin = pos
        marker = struct.unpack_from('<H', raw, pos)[0]
        if marker in (0, 0xFFFF):
            pos += 4 if marker else 2
            result.extend(raw[begin:pos])
            return
        while struct.unpack_from('<H', raw, pos)[0]:
            pos += 2
        original = raw[begin:pos].decode('utf-16le')
        pos += 2
        if translate:
            seen.add(original)
            if original in DIALOG_TEXT:
                original = convert(DIALOG_TEXT[original])
        if font:
            original = font_name
        result.extend((original + '\0').encode('utf-16le'))

    variable()
    variable()
    variable(translate=True)
    if style & 0x40:
        result.extend(raw[pos:pos+2])
        pos += 2
        variable(font=True)
    for _ in range(controls):
        pos = align(pos, 4)
        result.extend(b'\0' * (-len(result) % 4))
        result.extend(raw[pos:pos+18])
        pos += 18
        variable()
        variable(translate=True)
        extra = struct.unpack_from('<H', raw, pos)[0]
        count = extra or 2
        result.extend(raw[pos:pos+count])
        pos += count
    assert not set(DIALOG_TEXT) - seen, set(DIALOG_TEXT) - seen
    assert not any(raw[pos:])
    return bytes(result)


def resource_dialog(pe):
    group = next(entry for entry in pe.pe.DIRECTORY_ENTRY_RESOURCE.entries if entry.id == 5)
    item = next(entry for entry in group.directory.entries if str(entry.name) == 'IDD_START_DIALOG')
    return item.directory.entries[0].data.struct


def build(windows, dos, out, work, *, locale='zh-TW', memory_compatible=False):
    convert, font_name, charset = str, 'Microsoft JhengHei UI', b'\x88'
    if locale == 'zh-CN':
        from zh_cn import simplify
        convert, font_name, charset = simplify, 'Microsoft YaHei UI', b'\x86'
    source = original_exe(windows)
    pe = PE(source)
    if memory_compatible:
        # Reserve the added sections at a boundary VirtualAllocEx can use next
        # to the originally mapped image. Pad the final section in the file's layout.
        pe.next_rva = align(pe.next_rva, 0x10000)
        last = pe.pe.sections[-1]
        assert last.Name.rstrip(b'\0') == b'.rsrc'
        struct.pack_into('<I', pe.data, last.get_field_absolute_offset('Misc_VirtualSize'),
                         pe.next_rva - last.VirtualAddress)
    glyphs = Glyphs()
    records = []
    terms = []
    payload = bytearray()
    data_base = IMAGE_BASE + pe.next_rva

    def add(raw, alignment=1):
        payload.extend(b'\0' * (-len(payload) % alignment))
        address = data_base + len(payload)
        payload.extend(raw)
        return address

    main = dos_data(dos, 'MAIN.EXE')
    for row in story_rows(source, dos_data(dos, 'FQ4MES')):
        target, origin = localize_story(row, convert)
        cells = glyphs.cells(target)
        if len(cells) + 2 > BUFFER_SIZE:
            raise ValueError(f'Story ID {row["id"]} exceeds the message buffer')
        records.append(dict(**row, target=target, origin=origin, image=add((target + '\0').encode('utf-16le'), 2)))
    ptrs = add(b''.join(u32(row['image']) for row in records), 4)

    for row in table_rows(source, main):
        target, origin = localize_table(row)
        target = convert(target)
        pos, stride = row['win'], row['stride']
        if target:
            try:
                slot = fit(glyphs.cells(target), stride - 1, fullwidth=stride in (11, 13, 17, 27))
            except ValueError as error:
                raise ValueError((row['kind'], row['id'], target, str(error))) from error
            pe.data[pos:pos+stride] = slot + b'\0'
        terms.append(dict(**row, target=target, origin=origin))

    font = add((font_name + '\0').encode('ascii'))
    pe.patch(0x43D2D0, u32(0x4B9BCC), u32(font))
    pe.patch(0x43D304, b'\x80', charset)

    dialog = resource_dialog(pe)
    original_dialog = pe.pe.get_data(dialog.OffsetToData, dialog.Size)
    dialog_data = localize_dialog(original_dialog, convert, font_name)
    if memory_compatible:
        # Keep the startup template accessible through the original image's resource directory.
        if len(dialog_data) > dialog.Size:
            raise ValueError('The translated startup dialog exceeds its mapped resource slot')
        pe.patch(IMAGE_BASE + dialog.OffsetToData, original_dialog, dialog_data.ljust(dialog.Size, b'\0'))
        struct.pack_into('<I', pe.data, dialog.get_field_absolute_offset('Size'), len(dialog_data))
    else:
        dialog_address = add(dialog_data, 4)
        struct.pack_into('<II', pe.data, dialog.get_file_offset(), dialog_address - IMAGE_BASE, len(dialog_data))

    rules = dict(line.split('\t') for line in (ROOT / 'tools' / 'ui_terms.tsv').read_text(encoding='utf-8').splitlines())
    ui = patch_game_ui(pe, source, glyphs, {jp: convert(zh) for jp, zh in rules.items()})
    ui.extend(patch_diagnostics(pe, source, glyphs, add, convert))

    decode = add(struct.pack('<65536H', *glyphs.decode), 4)
    encode = add(glyphs.encoder(), 4)
    reverb = reverb_data(add)
    assert pe.section(b'.fq4text', payload, 0x40000040) == data_base
    patch_runtime(pe, source, decode, encode, ptrs, reverb)

    work.mkdir(parents=True, exist_ok=True)
    save_tsv(work / 'dialogue.tsv', records)
    save_tsv(work / 'terms.tsv', terms)
    save_tsv(work / 'ui.tsv', ui)
    evidence = list(dos_ui(main))
    save_tsv(work / 'ui-terms.tsv', (dict(ja=jp, target=convert(zh), dos_offsets=' '.join(
        f'0x{row["dos"]:x}' for row in evidence if zh.strip() and zh in row['zh'])) for jp, zh in rules.items()))
    out.mkdir(parents=True, exist_ok=True)
    for directory in ('DATA', 'PSDATA', 'BGM', 'FQ4HELP'):
        shutil.copytree(windows / directory, out / directory, dirs_exist_ok=True)
    shutil.copy2(windows / 'Readme.txt', out)
    temp = out / 'fq4.exe.new'
    temp.write_bytes(pe.data)
    temp.replace(out / 'fq4.exe')
    print('Dialogue:', dict(collections.Counter(row['origin'] for row in records)))
    print('Data tables:', dict(collections.Counter(row['origin'] for row in terms)))
    print(f'UI and diagnostics: {len(ui)} records')
    print(out / 'fq4.exe')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Build a Chinese FQ4 1.10 executable.')
    parser.add_argument('--win', type=Path, required=True, help='Windows Japanese v1.10 game directory')
    parser.add_argument('--dos', type=Path, required=True, help='Traditional Chinese DOS game directory')
    parser.add_argument('--locale', choices=('zh-TW', 'zh-CN'), default='zh-TW')
    parser.add_argument('--out', type=Path)
    parser.add_argument('--work', type=Path)
    args = parser.parse_args()
    if args.out is None:
        args.out = ROOT / 'dist' / ('FQ4-zh-CN' if args.locale == 'zh-CN' else 'FQ4')
    if args.work is None:
        args.work = WORK / ('build-zh-CN' if args.locale == 'zh-CN' else 'build')
    if any(args.out.resolve().is_relative_to(path.resolve()) for path in (args.win, args.dos)):
        parser.error('Choose a separate output folder outside both game installations.')
    build(args.win, args.dos, args.out, args.work, locale=args.locale)
