#!/usr/bin/python3
"""Record the real target runtime and verify an architecture-independent package."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import platform
import struct
import subprocess
import sys
import tarfile
import gi

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app_manager import __version__


def elf_machine(path):
    with Path(path).open('rb') as file:
        header = file.read(20)
    assert header[:4] == b'\x7fELF' and header[4] == 2, f'Expected native 64-bit ELF: {path}'
    return struct.unpack('<H' if header[5] == 1 else '>H', header[18:20])[0]


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--arch', choices=('amd64', 'arm64'), required=True)
parser.add_argument('--ubuntu', choices=('24.04', '26.04'), required=True)
parser.add_argument('--package', type=Path, required=True)
args = parser.parse_args()
architecture = subprocess.check_output(['dpkg', '--print-architecture'], text=True).strip()
machine = platform.machine()
expected_machine, expected_elf = {'amd64': ('x86_64', 62), 'arm64': ('aarch64', 183)}[args.arch]
assert architecture == args.arch and machine == expected_machine, (architecture, machine, args.arch)
release = platform.freedesktop_os_release()
assert release['ID'] == 'ubuntu' and release['VERSION_ID'] == args.ubuntu, release
python_elf = elf_machine(sys.executable)
gi_elf = elf_machine(gi._gi.__file__)
assert python_elf == gi_elf == expected_elf, (python_elf, gi_elf, expected_elf)
metadata = subprocess.check_output(['dpkg-deb', '-f', str(args.package), 'Package', 'Version', 'Architecture'], text=True)
fields = dict(line.split(': ', 1) for line in metadata.splitlines())
assert fields == {'Package': 'miemie-app-manager', 'Version': __version__, 'Architecture': 'all'}, fields
payload = subprocess.check_output(['dpkg-deb', '--fsys-tarfile', str(args.package)])
with tarfile.open(fileobj=io.BytesIO(payload)) as archive:
    files = [member for member in archive.getmembers() if member.isfile()]
    for member in files:
        assert not member.name.endswith(('.pyc', '.pyo')), member.name
        assert archive.extractfile(member).read(4) != b'\x7fELF', f'Native ELF cannot ship in an all package: {member.name}'
report = {'ubuntu': args.ubuntu, 'dpkg_architecture': architecture, 'machine': machine,
          'python_version': platform.python_version(), 'python_elf_machine': python_elf,
          'pygobject_elf_machine': gi_elf, 'package_architecture': 'all',
          'package_sha256': hashlib.sha256(args.package.read_bytes()).hexdigest(),
          'no_native_elf_or_bytecode_in_package': True, 'passed': True}
output = Path('.local/platform-report.json')
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(report, indent=2))
print(json.dumps(report))
