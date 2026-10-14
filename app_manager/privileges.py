"""Use only the packaged, root-owned helper for reusable authorization."""
from pathlib import Path
import json
import os
import pwd
import re
import stat

HELPER = Path('/usr/libexec/miemie-app-manager-helper')
POLICY = Path('/usr/share/polkit-1/actions/io.miemie.AppManager.policy')
AUTHORIZER = Path('/usr/libexec/miemie-app-manager-authorize')
AUTHORIZATION_STATE = Path('/var/lib/miemie-app-manager/authorizations')


def authorization_enabled():
    marker = AUTHORIZATION_STATE / f'{os.getuid()}.json'
    try:
        if not trusted_file(marker):
            return False
        data = json.loads(marker.read_text())
        return data == {'uid': os.getuid(), 'user': pwd.getpwuid(os.getuid()).pw_name, 'enabled': True}
    except (OSError, ValueError, KeyError):
        return False


def set_authorization(enabled, runner):
    if not trusted_file(AUTHORIZER, executable=True) or not trusted_file(POLICY):
        raise RuntimeError('请先安装新版星序系统包，再启用一次授权。')
    return runner(['/usr/bin/pkexec', str(AUTHORIZER), 'grant' if enabled else 'revoke'], timeout=120)


def trusted_file(path, executable=False):
    try:
        # Include every parent: a root-owned file in a writable directory is unsafe.
        for item in (path, *path.parents):
            info = item.lstat()
            if info.st_uid != 0 or info.st_mode & 0o022 or stat.S_ISLNK(info.st_mode):
                return False
        return path.is_file() and (not executable or os.access(path, os.X_OK))
    except OSError:
        return False


def helper_request(args):
    """Translate exact application commands, never arbitrary binaries or flags."""
    if args[:2] == ['/usr/bin/pkexec', '/usr/bin/apt-get']:
        tail = args[2:]
        if tail == ['-o', 'APT::Update::Error-Mode=any', '-o', 'Acquire::Retries=2', 'update']:
            return ['apt-refresh']
        if tail[:7] == ['-y', '--no-remove', '--only-upgrade', '-o', 'APT::Get::AutomaticRemove=false', 'install', '--'] and len(tail) == 8:
            package, sep, version = tail[-1].partition('=')
            if sep:
                return ['apt-upgrade', package, version]
        if len(tail) == 6 and tail[:5] == ['-y', '-o', 'APT::Get::AutomaticRemove=false', 'remove', '--']:
            return ['apt-remove', tail[-1]]
    if args[:2] == ['/usr/bin/pkexec', '/usr/bin/snap']:
        if len(args) == 4 and args[2] == 'remove':
            return ['snap-remove', args[3]]
        if len(args) == 5 and args[2] == 'refresh' and re.fullmatch(r'--revision=[0-9]+', args[4]):
            return ['snap-upgrade', args[3], args[4].split('=', 1)[1]]
    if args[:2] == ['/usr/bin/pkexec', '/usr/bin/flatpak']:
        if len(args) == 6 and args[2:5] == ['uninstall', '--system', '--noninteractive']:
            return ['flatpak-remove', args[5]]
        if len(args) == 8 and args[2:6] == ['update', '--system', '--app', '--noninteractive'] and args[6].startswith('--commit='):
            return ['flatpak-upgrade', args[7], args[6].split('=', 1)[1]]
    return None


def command_for(args, progress=False):
    request = helper_request(args)
    if request is not None and trusted_file(HELPER, executable=True) and trusted_file(POLICY):
        return ['/usr/bin/pkexec', str(HELPER), *request]
    # Source/user installs without the system helper retain normal per-command auth.
    if progress and args[:2] == ['/usr/bin/pkexec', '/usr/bin/apt-get']:
        return [*args[:2], '-o', 'APT::Status-Fd=1', '-o', 'Dpkg::Progress-Fancy=0', *args[2:]]
    return args
