import csv
from pathlib import Path

from ida_domain import Database
from ida_domain.database import IdaCommandOptions

import ida_bytes
import ida_funcs
import ida_lines
import ida_ua
import idautils


root = Path(r'D:\Games\FQ4C\work\ida')
out = root.parent / 'render-audit'
out.mkdir(parents=True, exist_ok=True)

addresses = {
    **{addr: 'sprite' for addr in range(0x4C6EC8, 0x4C6EF0)},
    0x5E9090: 'bitmap-font-texture', 0x5E91E4: 'd3dx-font-object',
    0x4891D4: 'DrawTextW', 0x4891D8: 'DrawTextA', 0x489030: 'CreateFontIndirectA',
    0x4891F0: 'MessageBox', 0x489240: 'DialogBoxParam', 0x48914C: 'LoadLibrary',
    0x489150: 'GetProcAddress', 0x437B20: 'draw-bitmap-text',
    0x437150: 'draw-hud-rows', 0x58D2AC: 'hud-row-x', 0x58D2AE: 'hud-row-y',
    0x52BDEC: 'unit-name-pointer', 0x57C320: 'frame-name-pointer',
    0x4B8968: 'short-spell-name', 0x437D90: 'draw-game-sprite',
    0x439750: 'draw-standby-panel', 0x4B99F0: 'standby-label',
}

with Database.open(str(root / 'win.i64'), IdaCommandOptions(auto_analysis=False), save_on_close=False) as db:
    with (out / 'render-references.tsv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.writer(stream, delimiter='\t')
        writer.writerow(('symbol', 'address', 'use', 'function', 'instruction'))
        for address, name in addresses.items():
            for ea in sorted({xref.from_ea for xref in db.xrefs.to_ea(address)}):
                func = ida_funcs.get_func(ea)
                insn = ida_lines.tag_remove(ida_lines.generate_disasm_line(ea, 0) or '')
                writer.writerow((name, hex(address), hex(ea), hex(func.start_ea) if func else '', insn))

    # Also match addresses inside instruction operands. IDA may record a
    # reference against the base of an array instead of the particular field.
    with (out / 'sprite-operands.tsv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.writer(stream, delimiter='\t')
        writer.writerow(('sprite_field', 'use', 'function', 'operand', 'instruction'))
        insn = ida_ua.insn_t()
        for fn in idautils.Functions():
            for ea in idautils.FuncItems(fn):
                if not ida_bytes.is_code(ida_bytes.get_full_flags(ea)) or not ida_ua.decode_insn(insn, ea):
                    continue
                for i, operand in enumerate(insn.ops):
                    if operand.type in (ida_ua.o_mem, ida_ua.o_displ) and 0x4C6EC8 <= operand.addr < 0x4C6EF0:
                        text = ida_lines.tag_remove(ida_lines.generate_disasm_line(ea, 0) or '')
                        writer.writerow((hex(operand.addr), hex(ea), hex(fn), i, text))
