from pathlib import Path
from ida_domain import Database
from ida_domain.database import IdaCommandOptions
import ida_hexrays
import ida_kernwin
import ida_loader
import ida_lines

root = Path(r"D:\Games\FQ4C\work\ida")
requests = {}
for field in (root / "dump_requests.txt").read_text().split():
    addr = int(field.lstrip("+"),16)
    requests[addr] = field.startswith("+")
with Database.open(str(root/"win.i64"), IdaCommandOptions(auto_analysis=False), save_on_close=False) as db:
    ready = ida_hexrays.init_hexrays_plugin()
    if not ready:
        ida_loader.load_plugin("hexx64")
        ready = ida_hexrays.init_hexrays_plugin()
    print("Hex-Rays:",ready)
    for addr, full in requests.items():
        func = db.functions.get_at(addr)
        if not func:
            print(hex(addr),"missing")
            continue
        with (root / f"{addr:06x}.txt").open("w",encoding="utf-8") as out:
            name = db.functions.get_name(func)
            print(hex(func.start_ea),hex(func.end_ea),name,file=out)
            refs = [(hex(x.from_ea), hex(f.start_ea) if (f:=db.functions.get_at(x.from_ea)) else "") for x in db.xrefs.to_ea(func.start_ea)]
            print("xrefs:",list(dict.fromkeys(refs)),file=out)
            try:
                result = db.functions.get_pseudocode(func)
                if result:
                    print(result,file=out)
                    if not full:
                        continue
            except Exception as e:
                print(str(e),file=out)
            for ins in db.functions.get_instructions(func):
                print(f"{ins.ea:08x}",ida_lines.tag_remove(ida_lines.generate_disasm_line(ins.ea,0) or ""),file=out)
