import re
import struct

from captions import emit_caption_hooks, emit_status_name
from reverb import emit_reverb_fallback


IMAGE_BASE = 0x400000
MESSAGE_BUFFER = 0x57A7E4
BUFFER_SIZE = 768


def u32(value):
    return struct.pack('<I', value)


def call(source, target):
    return b'\xe8' + struct.pack('<i', target - source - 5)


class Code:
    def __init__(self, base):
        self.base = base
        self.data = bytearray()
        self.labels = {}
        self.branches = []

    def emit(self, hex_bytes, address=None):
        self.data.extend(bytes.fromhex(hex_bytes))
        if address is not None:
            self.data.extend(u32(address))

    def label(self, name):
        self.labels[name] = len(self.data)
        return self.base + len(self.data)

    def relative(self, opcode, label, size=1):
        self.emit(opcode)
        self.branches.append((len(self.data), label, size))
        self.data.extend(b'\0' * size)

    def to_address(self, opcode, address):
        instruction = bytes.fromhex(opcode)
        offset = address - (self.base + len(self.data) + len(instruction) + 4)
        self.data.extend(instruction + struct.pack('<i', offset))

    def finish(self):
        for pos, label, size in self.branches:
            distance = self.labels[label] - pos - size
            self.data[pos:pos+size] = distance.to_bytes(size, 'little', signed=True)
        return self.data


def patch_runtime(pe, source, glyph_decode, glyph_encode, message_table, reverb):
    base = IMAGE_BASE + pe.next_rva
    code = Code(base)

    # The new message table is pointer-indexed UTF-16. The dialogue parser still
    # expects single-byte layout controls and two-byte glyph cells in its buffer.
    message_load = code.label('message_load')
    code.emit('0f b7 44 24 04 3d 1f 03 00 00')  # movzx eax, word [esp+4]; cmp eax,799
    code.relative('76', 'message_slot')
    code.emit('c3')
    code.label('message_slot')
    code.emit('56 57')  # push esi; push edi
    code.emit('0f b7 14 45', 0x4986D8)  # Preserve the original scratch offset.
    code.emit('66 89 15', 0x52A2B4)
    code.emit('8b 34 85', message_table)  # mov esi,[message_table+eax*4]
    code.emit('bf', MESSAGE_BUFFER)
    code.label('message_next')
    code.emit('0f b7 0e 66 85 c9')  # movzx ecx,word [esi]; test cx,cx
    code.relative('74', 'message_end')
    code.emit('83 c6 02 0f b7 14 4d', glyph_encode)
    code.emit('88 17 47 84 f6')  # Store low byte; add high byte for a two-byte cell.
    code.relative('74', 'message_next')
    code.emit('88 37 47')
    code.relative('eb', 'message_next')
    code.label('message_end')
    code.emit('66 c7 07 00 00 d1 e0 5f 5e c3')

    # Text sprites (type 10) now carry UTF-16 in the former CP932 glyph field.
    # The other sprite types share this field for unrelated tile indices.
    sprite_eax = code.label('sprite_eax')
    code.emit('51 0f b7 88', 0x4C6ED4)  # push ecx; movzx ecx,word [eax+glyph]
    code.emit('66 8b 0c 4d', glyph_decode)
    code.emit('66 89 88', 0x4C6ED4)
    code.emit('59 66 c7 80', 0x4C6EEE)
    code.emit('0a 00 c3')
    sprite_ecx = code.label('sprite_ecx')
    code.emit('50 0f b7 81', 0x4C6ED4)  # push eax; movzx eax,word [ecx+glyph]
    code.emit('66 8b 04 45', glyph_decode)
    code.emit('66 89 81', 0x4C6ED4)
    code.emit('58 66 c7 81', 0x4C6EEE)
    code.emit('0a 00 c3')

    # MessageBoxA callers pass char buffers, including sprintf and file paths.
    # Adapt those buffers to UTF-16 separately from the game's sprite pipeline.
    message_box = code.label('message_box')
    code.emit('55 8b ec 56 57 81 ec 00 0a 00 00')  # 1024 + 256 WCHARs
    code.emit('8b 75 0c 8d bd f8 f7 ff ff b9 ff 03 00 00')
    code.relative('e8', 'convert', 4)
    code.emit('8b 75 10 8d bd f8 f5 ff ff b9 ff 00 00 00')
    code.relative('e8', 'convert', 4)
    code.emit('ff 75 14 8d 85 f8 f5 ff ff 50 8d 85 f8 f7 ff ff 50 ff 75 08')
    code.emit('ff 15', 0x4891F0)  # MessageBoxW
    code.emit('8d 65 f8 5f 5e 5d c2 10 00')

    code.label('convert')
    code.emit('85 f6')
    code.relative('74', 'convert_end')
    code.label('convert_next')
    code.emit('0f b6 06 46 84 c0')  # movzx eax,byte [esi]; inc esi; test al,al
    code.relative('74', 'convert_end')
    code.emit('3c 80')
    code.relative('72', 'convert_store')
    code.emit('3c a1')
    code.relative('72', 'convert_pair')
    code.emit('3c df')
    code.relative('77', 'convert_pair')
    code.emit('05', 0xFF61 - 0xA1)  # Halfwidth punctuation and kana.
    code.relative('eb', 'convert_store')
    code.label('convert_pair')
    code.emit('8a 26 84 e4')  # mov ah,[esi]; test ah,ah
    code.relative('74', 'convert_truncated')
    code.emit('46 0f b7 04 45', glyph_decode)
    code.relative('eb', 'convert_store')
    code.label('convert_truncated')
    code.emit('b8', 0xFFFD)
    code.label('convert_store')
    code.emit('66 ab')  # stosw
    code.relative('e2', 'convert_next')
    code.label('convert_end')
    code.emit('33 c0 66 ab c3')

    reverb_fallback = emit_reverb_fallback(code, *reverb)
    caption_name, caption_spell = emit_caption_hooks(code, glyph_decode)
    status_name = emit_status_name(code)

    assert pe.section(b'.fq4uni', code.finish(), 0x60000020) == base
    pe.patch(0x443657, bytes.fromhex('85c05f7415'), b'\xe9' + struct.pack('<i', reverb_fallback - 0x44365C))
    for address, stub, original in ((0x40FAAF, caption_name, '3c20894c2410'),
                                    (0x40FD7A, caption_spell, '3c2089542410')):
        pe.patch(address, bytes.fromhex(original), b'\xe9' + struct.pack('<i', stub - address - 5) + b'\x90')
    pe.patch(0x437732, bytes.fromhex('668b026689442444'),
             b'\xe9' + struct.pack('<i', status_name - 0x437737) + b'\x90' * 3)
    pe.patch(0x418060, bytes.fromhex('8b44240466'), b'\xe9' + struct.pack('<i', message_load - 0x418065))
    for addr, stub, original in ((0x40D0BA, sprite_eax, '66c780ee6e4c000a00'),
                                  (0x40D1DB, sprite_eax, '66c780ee6e4c000a00'),
                                  (0x40E625, sprite_ecx, '66c781ee6e4c000a00')):
        pe.patch(addr, bytes.fromhex(original), call(addr, stub) + b'\x90' * 4)
    pe.patch(0x43896B, b'\x81\x40', b'\x00\x30')  # UTF-16 ideographic space
    pe.patch(0x438A7E, b'\x02', b'\x01')  # one UTF-16 code unit
    pe.patch(0x438A83, b'\x18', b'\x1c')  # DrawTextW vtable slot
    pe.patch(0x439A7A, b'\x18', b'\x1c')  # Standby panel label is also UTF-16.

    api = next(imp for dll in pe.pe.DIRECTORY_ENTRY_IMPORT for imp in dll.imports if imp.name == b'MessageBoxA')
    pe.patch(IMAGE_BASE + pe.pe.get_rva_from_offset(api.name_offset), b'MessageBoxA', b'MessageBoxW')
    refs = list(re.finditer(re.escape(u32(api.address)), source[0x1000:0x8822E]))
    assert len(refs) == 16
    for match in refs:
        off = 0x1000 + match.start() - 2
        pos = IMAGE_BASE + off
        op = source[off:off+2]
        if op == b'\xff\x15':
            redirect = call(pos, message_box)
        elif op == b'\x8b\x2d':
            redirect = b'\xbd' + u32(message_box)  # mov ebp, message_box
        else:
            raise ValueError(f'Unexpected MessageBoxA reference at {pos:x}')
        pe.patch(pos, op + u32(api.address), redirect + b'\x90')
