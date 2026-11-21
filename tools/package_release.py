import argparse
import re
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pefile

from catalog import ROOT

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


def project_version():
    with (ROOT / 'pyproject.toml').open('rb') as project:
        version = tomllib.load(project)['project']['version']
    if not re.fullmatch(r'(?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*)){2}', version):
        raise ValueError(f'Expected a stable SemVer version, got {version!r}')
    if any(int(part) > 0xFFFF for part in version.split('.')):
        raise ValueError(f'Version {version} exceeds the Windows version resource limit')
    return version


def package_release(patcher, tag, output_dir):
    version = project_version()
    if tag != f'v{version}':
        raise ValueError(f'Tag {tag!r} must match the project version v{version}')
    major, minor, patch = map(int, version.split('.'))
    with pefile.PE(str(patcher)) as image:
        versions = getattr(image, 'VS_FIXEDFILEINFO', [])
        if (image.FILE_HEADER.Machine != pefile.MACHINE_TYPE['IMAGE_FILE_MACHINE_I386']
                or not versions
                or (versions[0].FileVersionMS, versions[0].FileVersionLS)
                != ((major << 16) | minor, patch << 16)):
            raise ValueError(f'Expected an x86 patcher EXE with file version {version}: {patcher}')

    changelog = ROOT / 'CHANGELOG.md'
    notes = re.search(rf'^## \[{re.escape(version)}\] - \d{{4}}-\d{{2}}-\d{{2}}\n'
                      r'([\s\S]*?)(?=^## |^\[[^]\n]+\]:|\Z)',
                      changelog.read_text(encoding='utf-8'), re.MULTILINE)
    if not notes or not notes[1].strip():
        raise ValueError(f'CHANGELOG.md has no release notes for {version}')

    output_dir.mkdir(parents=True, exist_ok=True)
    archive = output_dir / f'FQ4ChinesePatch-{tag}.zip'
    with tempfile.TemporaryDirectory(dir=output_dir) as temp:
        stage = Path(temp) / archive.name
        with ZipFile(stage, 'w', compression=ZIP_DEFLATED) as bundle:
            for name in ('CHANGELOG.md', 'README.md', 'LICENSE',
                         'docs/FQ4-manual-zh-Hans.html', 'docs/FQ4-manual-zh-Hant.html'):
                bundle.write(ROOT / name, name)
            bundle.write(patcher, 'FQ4ChinesePatch.exe')
        stage.replace(archive)
    (output_dir / 'release-notes.md').write_text(notes[1].strip() + '\n', encoding='utf-8')
    print(archive)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Package a versioned FQ4 Chinese patch release.')
    parser.add_argument('--tag', required=True)
    parser.add_argument('--patcher', type=Path, default=ROOT / 'dist' / 'FQ4ChinesePatch.exe')
    parser.add_argument('--out-dir', type=Path, default=ROOT / 'dist')
    args = parser.parse_args()
    package_release(args.patcher, args.tag, args.out_dir)
