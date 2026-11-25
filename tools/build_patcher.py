import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pefile

from build import build
from catalog import ROOT, WORK, original_exe
from package_release import project_version


PATCHER = ROOT / 'tools' / 'patcher'
BUILD_DIR = WORK / 'patcher'


def changed_spans(before, after, start, stop):
    first = last = None
    for offset in range(start, stop):
        if before[offset] == after[offset]:
            continue
        if last is not None and offset - last > 9:
            yield first, last + 1
            first = None
        if first is None:
            first = offset
        last = offset
    if first is not None:
        yield first, last + 1


def make_payload(original, chinese, work, locale):
    before = pefile.PE(data=original)
    after = pefile.PE(data=chinese)
    original_sections = len(before.sections)
    data, code = after.sections[original_sections:]
    assert data.Name.rstrip(b'\0') == b'.fq4text' and code.Name.rstrip(b'\0') == b'.fq4uni'
    image_base = before.OPTIONAL_HEADER.ImageBase
    assert image_base == after.OPTIONAL_HEADER.ImageBase
    assert data.VirtualAddress >= before.OPTIONAL_HEADER.SizeOfImage
    assert (image_base + data.VirtualAddress) % 0x10000 == 0

    disk_only = 0xFFFFFFFF
    records = []
    payload = bytearray()

    def add(start, stop, rva):
        records.append((start, rva, stop - start))
        payload.extend(chinese[start:stop])

    # The file offset and RVA differ for .rsrc. Headers and file padding are
    # applied only to the disk output, so the Windows loader sees its own image layout.
    cursor = 0
    for base, localized in zip(before.sections, after.sections):
        assert base.Name == localized.Name
        assert base.VirtualAddress == localized.VirtualAddress
        start, size = base.PointerToRawData, base.SizeOfRawData
        assert (start, size) == (localized.PointerToRawData, localized.SizeOfRawData)
        for first, end in changed_spans(original, chinese, cursor, start):
            add(first, end, disk_only)
        cursor = start + size
        for first, end in changed_spans(original, chinese, start, cursor):
            add(first, end, localized.VirtualAddress + first - start)
    for first, end in changed_spans(original, chinese, cursor, len(original)):
        add(first, end, disk_only)
    for section in (data, code):
        start = section.PointerToRawData
        add(start, start + section.SizeOfRawData, section.VirtualAddress)

    # Check the embedded records by reconstructing the full output, including file padding.
    reconstructed = bytearray(original)
    reconstructed.extend(bytes(len(chinese) - len(original)))
    cursor = 0
    for file_offset, _, size in records:
        reconstructed[file_offset:file_offset + size] = payload[cursor:cursor + size]
        cursor += size
    assert reconstructed == chinese

    message_box = next(imp for dll in before.DIRECTORY_ENTRY_IMPORT for imp in dll.imports
                       if imp.name == b'MessageBoxA')
    thunk_rva = message_box.address - image_base
    values = {
        'kDiskOnly': disk_only,
        'kImageBase': image_base,
        'kHeadersSize': before.OPTIONAL_HEADER.SizeOfHeaders,
        'kSourceSize': len(original),
        'kTargetSize': len(chinese),
        'kPayloadSize': len(payload),
        'kExtensionRva': data.VirtualAddress,
        'kExtensionSize': after.OPTIONAL_HEADER.SizeOfImage - data.VirtualAddress,
        'kCodeRva': code.VirtualAddress,
        'kCodeSize': code.SizeOfRawData,
        'kMessageBoxThunkRva': thunk_rva,
        'kMessageBoxThunkOffset': before.get_offset_from_rva(thunk_rva),
    }
    simplified = locale == 'zh-CN'
    namespace = 'zh_cn' if simplified else 'zh_tw'
    suffix = '_cn' if simplified else ''
    lines = ['#pragma once', '', f'namespace {namespace} {{']
    for name, value in values.items():
        lines.append(f'inline constexpr std::uint32_t {name} = 0x{value:x};')
    hashes = {}
    for name, binary in (('Source', original), ('Target', chinese)):
        digest = hashlib.sha256(binary).digest()
        hashes[name.lower() + '_sha256'] = digest.hex()
        formatted = ', '.join(f'0x{value:02x}' for value in digest)
        lines.append(f'inline constexpr std::array<std::uint8_t, 32> k{name}Hash{{{formatted}}};')
    lines.extend(['', 'inline constexpr PatchRecord kRecords[] = {'])
    lines.extend(f'    {{0x{offset:x}, 0x{rva:x}, 0x{size:x}}},' for offset, rva, size in records)
    lines.extend([
        '};', '', 'inline constexpr PatchData kPatch{',
        '    kTargetSize, kPayloadSize, kExtensionRva, kExtensionSize, kCodeRva, kCodeSize,',
        f'    kTargetHash, kRecords, kRecords + {len(records)}',
        '};', f'}}  // namespace {namespace}',
    ])
    (work / f'patch_data{suffix}.hpp').write_text('\n'.join(lines) + '\n', encoding='ascii')
    (work / f'payload{suffix}.bin').write_bytes(payload)
    (work / f'payload{suffix}.json').write_text(json.dumps({
        **hashes, 'records': len(records), 'payload_bytes': len(payload),
        'extension_address': hex(image_base + data.VirtualAddress),
        'extension_bytes': values['kExtensionSize'],
    }, indent=2) + '\n', encoding='utf-8')


def build_patcher(windows, dos, output, work, *, payload_dir=None):
    if not shutil.which('cl.exe') or not shutil.which('rc.exe'):
        raise SystemExit('Run the build from an x86 Native Tools Command Prompt for Visual Studio.')
    version = project_version()
    work.mkdir(parents=True, exist_ok=True)
    if payload_dir is None:
        original = original_exe(windows)
        for locale, suffix in (('zh-TW', ''), ('zh-CN', '-zh-CN')):
            image = work / ('image' + suffix)
            build(windows, dos, image, work / ('translation' + suffix),
                  locale=locale, memory_compatible=True)
            make_payload(original, (image / 'fq4.exe').read_bytes(), work, locale)
    else:
        for name in ('patch_data.hpp', 'patch_data_cn.hpp', 'payload.bin', 'payload_cn.bin'):
            shutil.copyfile(payload_dir / name, work / name)

    numbers = ','.join(version.split('.') + ['0'])
    (work / 'patcher_version.h').write_text(
        f'#define FQ4_VERSION "{version}"\n'
        f'#define FQ4_VERSION_NUMERIC {numbers}\n'
        f'#define FQ4_HEADER "First Queen IV  /  v{version}"\n',
        encoding='utf-8')

    resources = work / 'patcher.res'
    subprocess.run(['rc.exe', '/nologo', '/fo', str(resources), '/I', str(work),
                    str(PATCHER / 'patcher.rc')], cwd=work, check=True)
    candidate = work / 'FQ4ChinesePatch.exe'
    subprocess.run(['cl.exe', '/nologo', '/std:c++17', '/utf-8', '/O2', '/MT', '/EHsc', '/W4', '/WX',
                    '/I' + str(work), '/Fo' + str(work / 'patcher.obj'), '/Fe' + str(candidate),
                    str(PATCHER / 'patcher.cpp'), str(resources),
                    '/link', '/SUBSYSTEM:WINDOWS', '/MACHINE:X86', '/MANIFEST:EMBED',
                    'bcrypt.lib', 'comdlg32.lib', 'gdi32.lib', 'user32.lib'], cwd=work, check=True)
    if output != candidate:
        output.parent.mkdir(parents=True, exist_ok=True)
        stage = output.with_name(output.name + '.new')
        shutil.copy2(candidate, stage)
        stage.replace(output)
    print(output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Build the standalone First Queen IV Chinese patcher.')
    parser.add_argument('--win', type=Path, help='Windows Japanese v1.10 game directory')
    parser.add_argument('--dos', type=Path, help='Traditional Chinese DOS game directory')
    parser.add_argument('--payload-dir', type=Path, help='Directory containing the generated patch data')
    parser.add_argument('--out', type=Path, default=ROOT / 'dist' / 'FQ4ChinesePatch.exe')
    parser.add_argument('--work', type=Path, default=BUILD_DIR)
    args = parser.parse_args()
    if args.payload_dir is None:
        if args.win is None or args.dos is None:
            parser.error('Specify both --win and --dos, or use --payload-dir.')
        build_patcher(args.win.resolve(), args.dos.resolve(), args.out.resolve(), args.work.resolve())
    else:
        if args.win is not None or args.dos is not None:
            parser.error('--payload-dir cannot be combined with --win or --dos.')
        if args.payload_dir.resolve() == args.work.resolve():
            parser.error('Choose different directories for --payload-dir and --work.')
        build_patcher(None, None, args.out.resolve(), args.work.resolve(),
                      payload_dir=args.payload_dir.resolve())
