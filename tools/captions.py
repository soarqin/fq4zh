def emit_caption_hooks(code, glyph_decode):
    # The map-frame name and the adjacent spell label both budget eight bytes.
    name = code.label('map_frame_name')
    code.emit('89 4c 24 10 84 c0')  # Keep the next byte pointer; stop at NUL.
    code.to_address('0f 84', 0x40FBC0)
    code.emit('83 7c 24 14 07')
    code.relative('73', 'name_bitmap')
    code.relative('e8', 'caption_pair', 4)
    code.relative('73', 'name_bitmap')
    code.emit('ff 44 24 10 8d 56 10 39 ea')  # Consume the trail byte and check the right edge.
    code.relative('7f', 'name_advance')
    code.emit('83 ff 10')  # The Unicode sprite fills a 16-pixel row.
    code.relative('72', 'name_advance')
    code.emit('68 f0 00 00 00 ff 74 24 34')  # Original black palette index and y.
    code.relative('e8', 'caption_sprite', 4)
    code.label('name_advance')
    code.emit('83 c6 08 83 44 24 20 08 ff 44 24 14')
    code.to_address('e9', 0x40FBA0)  # The original loop advances the other eight pixels.
    code.label('name_bitmap')
    code.emit('3c 20')
    code.to_address('e9', 0x40FAB5)

    spell = code.label('map_frame_spell')
    code.emit('89 54 24 10 84 c0')
    code.to_address('0f 84', 0x40FE91)
    code.emit('83 7c 24 14 07')
    code.relative('73', 'spell_bitmap')
    code.emit('51 89 d1')  # The spell loop keeps its y limit in ecx.
    code.relative('e8', 'caption_pair', 4)
    code.emit('59')
    code.relative('73', 'spell_bitmap')
    code.emit('ff 44 24 10 8d 56 10 3b 54 24 1c')
    code.relative('7f', 'spell_advance')
    code.emit('83 7c 24 20 10')
    code.relative('72', 'spell_advance')
    code.emit('6a 00 57')  # Original white palette index and y.
    code.relative('e8', 'caption_sprite', 4)
    code.label('spell_advance')
    code.emit('83 c6 08 83 44 24 30 08 ff 44 24 14 8b 4c 24 24')
    code.to_address('e9', 0x40FE6D)
    code.label('spell_bitmap')
    code.emit('3c 20')
    code.to_address('e9', 0x40FD80)

    # AL is the first byte and ECX points at the second. A valid pair
    # returns its UTF-16 code unit in EAX and sets carry.
    code.label('caption_pair')
    for limit, branch, label in (('81', '72', 'caption_single'), ('9f', '76', 'caption_trail'),
                                  ('e0', '72', 'caption_single'), ('fc', '77', 'caption_single')):
        code.emit('3c ' + limit)
        code.relative(branch, label)
    code.label('caption_trail')
    code.emit('8a 21')
    for limit, branch in (('40', '72'), ('7f', '74'), ('fc', '77')):
        code.emit('80 fc ' + limit)
        code.relative(branch, 'caption_single')
    code.emit('0f b7 c0 0f b7 04 45', glyph_decode)
    code.emit('f9 c3')
    code.label('caption_single')
    code.emit('f8 c3')

    # Use the game's Unicode text sprite, with the same window, sort order
    # and scale as its bitmap captions. ESI is x and EBX is the window index.
    code.label('caption_sprite')
    code.emit('0f b7 0d', 0x53E672)
    code.emit('6b c9 28')
    code.emit('66 89 81', 0x4C6ED4)  # glyph
    code.emit('66 89 b1', 0x4C6ECC)  # x
    code.emit('8b 54 24 04 66 89 91', 0x4C6ECE)  # y
    code.emit('8b 54 24 08 66 89 91', 0x4C6ED8)  # palette
    code.emit('c7 81', 0x4C6ED0)
    code.emit('10 00 10 00')
    code.emit('31 d2 89 91', 0x4C6EC8)
    code.emit('89 91', 0x4C6EE8)
    code.emit('66 c7 81', 0x4C6EDA)
    code.emit('fd 01')
    code.emit('c7 81', 0x4C6EE4)
    code.emit('00 10 00 10')
    code.emit('88 99', 0x4C6EEC)
    code.emit('66 c7 81', 0x4C6EEE)
    code.emit('0a 00')
    code.emit('66 ff 05', 0x53E672)
    code.emit('66 ff 04 5d', 0x547874)
    code.emit('c2 08 00')
    return name, spell


def emit_status_name(code):
    # The battle status rows draw directly before the sprite list. EDX is the
    # full name pointer, EBP is the column's x and EBX is its y.
    entry = code.label('status_name')
    code.emit('55 56 57 83 ec 18 89 d6 89 ef 83 c5 20')
    code.emit('c6 44 24 14 03')  # Keep the original three-character abbreviation.
    code.label('status_name_next')
    code.emit('39 ef')  # At most 32 pixels per member, including mixed-width names.
    code.relative('0f 8d', 'status_name_end', 4)
    code.emit('0f b6 06 46 84 c0')
    code.relative('0f 84', 'status_name_end', 4)
    code.emit('89 f1')
    code.relative('e8', 'caption_pair', 4)
    code.relative('73', 'status_name_bitmap')
    code.emit('8d 57 10 39 ea')
    code.relative('7f', 'status_name_end')
    code.emit('46 89 04 24')  # Store one UTF-16 character followed by a NUL.
    code.emit('89 7c 24 04 89 5c 24 08 89 54 24 0c 8d 4b 10 89 4c 24 10')  # RECT

    # Same font object, palette and DrawTextW call as a Unicode sprite.
    code.emit('a1', 0x5E91E4)
    code.emit('50 8b 08 ff 51 14')  # Begin
    code.emit('a1', 0x5E91E4)
    code.emit('8b 10 8d 4c 24 04')  # vtable, RECT
    code.emit('ff 35', 0x4B9780)  # Palette color 15
    code.emit('68 00 01 00 00 51 6a 01 8d 4c 24 10 51 50')  # flags, RECT, count, WCHAR, this
    code.emit('ff 52 1c')  # DrawTextW
    code.emit('a1', 0x5E91E4)
    code.emit('50 8b 10 ff 52 20 83 c7 10')  # End; advance one wide cell.
    code.relative('eb', 'status_name_advance')

    code.label('status_name_bitmap')
    code.emit('0f b6 c0 89 04 24 89 e0 50 6a 0f 53 57')
    code.to_address('e8', 0x437B20)
    code.emit('83 c4 10 83 c7 08')
    code.label('status_name_advance')
    code.emit('fe 4c 24 14')
    code.relative('0f 85', 'status_name_next', 4)
    code.label('status_name_end')
    code.emit('83 c4 18 5f 5e 5d')
    code.to_address('e9', 0x437757)
    return entry
