import struct


def emit_name_cells(code):
    # EDX points to a name. Return the next fullwidth cell in AX and advance EDX.
    # Fixed-length fields keep their width by padding after the terminator.
    code.label('next_name_cell')
    code.emit('0f b6 02 84 c0')  # movzx eax,byte ptr [edx]; test al,al
    code.relative('74', 'name_padding')
    code.emit('3c 81')
    code.relative('72', 'name_widen')
    code.emit('3c 9f')
    code.relative('76', 'name_trail')
    code.emit('3c e0')
    code.relative('72', 'name_widen')
    code.emit('3c fc')
    code.relative('77', 'name_widen')
    code.label('name_trail')
    for limit, branch in (('40', '72'), ('7f', '74'), ('fc', '77')):
        code.emit('80 7a 01 ' + limit)  # cmp byte ptr [edx+1], limit
        code.relative(branch, 'name_widen')
    code.emit('8a 62 01 83 c2 02 c3')  # mov ah,[edx+1]; add edx,2; ret
    code.label('name_padding')
    code.emit('b8 81 40 00 00 c3')  # Fullwidth space; leave EDX at the terminator.
    code.label('name_widen')
    code.emit('42 52 50')  # Advance and save EDX across the original converter.
    code.to_address('e8', 0x435430)
    code.emit('83 c4 04 5a c3')

    readers = {}
    for register, setup, update in (
            ('ebx', '89 da', '89 d3'), ('ebp', '89 ea', '89 d5'), ('edi', '89 fa', '89 d7')):
        readers[register] = code.label(f'name_cell_{register}')
        code.emit(setup)
        code.relative('e8', 'next_name_cell', 4)
        code.emit(update + ' c3')

    indexed = code.label('indexed_name')
    # The indexed roster writes nine cells, starting at name_table[EDI].
    code.emit('8d 3c bf 8d 3c 7d', 0x4B46B8)  # EDI = name_table + EDI * 10.
    code.emit('bd 09 00 00 00')
    code.label('indexed_name_next')
    code.relative('e8', 'name_cell_edi', 4)
    code.emit('66 89 06 66 a3', 0x52A230)
    code.emit('83 c6 02 4d')  # Advance destination and decrement the cell count.
    code.relative('75', 'indexed_name_next')
    code.to_address('e9', 0x42F8C2)
    return readers, indexed


def patch_name_cells(pe, readers, indexed):
    # Replace the source increment and widening call together. Keep one stack
    # argument for the original caller's cleanup and preserve its field layout.
    for register, sites in (
        ('edi', ((0x40895D, '5047'), (0x40A801, '5047'), (0x413BF6, '4750'),
                 (0x42E225, '4750'), (0x42FEE7, '4750'), (0x4302E8, '4750'),
                 (0x430647, '4750'), (0x4405FF, '4750'))),
        ('ebx', ((0x416C64, '5043'), (0x416ED6, '5043'), (0x4305C5, '4350'),
                 (0x430606, '4350'))),
        ('ebp', ((0x416DE2, '5045'), (0x4229D8, '5045'), (0x42F12E, '4550'),
                 (0x42FE97, '4550'))),
    ):
        for address, prefix in sites:
            original = bytes.fromhex(prefix + 'e8') + struct.pack('<i', 0x435430 - (address + 7))
            replacement = b'\x50\xe8' + struct.pack('<i', readers[register] - (address + 6)) + b'\x90'
            pe.patch(address, original, replacement)

    original = bytes.fromhex('8d2cbf33ff8a846fb8464b0050e8895b000083c404880666a330a25200'
                             '8a0d31a2520046880e464783ff097cd8')
    jump = b'\xe9' + struct.pack('<i', indexed - 0x42F89A)
    pe.patch(0x42F895, original, jump.ljust(len(original), b'\x90'))
