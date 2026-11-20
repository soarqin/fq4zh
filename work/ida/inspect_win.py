from pathlib import Path
import sys
sys.stdout.reconfigure(encoding="utf-8")
from ida_domain import Database
from ida_domain.database import IdaCommandOptions

root = Path(r"D:\Games\FQ4C\work\ida")
src = r"D:\Games\FQ4\fq4.exe"
with Database.open(src, IdaCommandOptions(auto_analysis=True, new_database=True, output_database=str(root / "win.i64"), load_resources=True), save_on_close=True) as db:
    addresses = [0x4891d4, 0x4891d8, 0x4891f0, 0x489030, 0x48913c, 0x49805c, 0x498d18, 0x498d2c, 0x4986d8, 0x498648, 0x4986d4]
    items = set()
    with (root / "xref.txt").open("w", encoding="utf-8") as out:
        for addr in addresses:
            refs = []
            for ref in db.xrefs.to_ea(addr):
                func = db.functions.get_at(ref.from_ea)
                if func:
                    items.add(func.start_ea)
                refs.append((hex(ref.from_ea), hex(func.start_ea) if func else None))
            print(hex(addr), refs, file=out)
        for addr in sorted(items):
            func = db.functions.get_at(addr)
            print(f"\n{addr:08x}", db.functions.get_name(func), [(hex(x.start_ea),db.functions.get_name(x)) for x in db.functions.get_callers(func)], file=out)
            try:
                print("\n".join(db.functions.get_pseudocode(func)), file=out)
            except Exception as e:
                print(e, file=out)
    with (root / "refs.tsv").open("w", encoding="utf-8") as out:
        for x in db.heads.get_between(0x489000, 0x4c7000):
            if not (refs := list(db.xrefs.to_ea(x))):
                continue
            print(f"{x:x}", *[f"{ref.from_ea:x}" for ref in refs], sep="\t", file=out)
    with (root / "functions.tsv").open("w", encoding="utf-8") as out:
        for func in db.functions:
            print(f"{func.start_ea:x}", f"{func.end_ea:x}", db.functions.get_name(func), sep="\t", file=out)
