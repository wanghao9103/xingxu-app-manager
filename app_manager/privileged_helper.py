#!/usr/bin/python3 -I
"""Packaged root helper. No shell, imported app code, caller flags or paths.

Installed as /usr/libexec/miemie-app-manager-helper; the polkit action applies
only to this executable. Validate every request because authorization is cached.
"""
import os
import re
import subprocess
import sys

APT = '/usr/bin/apt-get'
APT_OPTIONS = ['-o', 'APT::Status-Fd=1', '-o', 'Dpkg::Progress-Fancy=0',
               '-o', 'APT::Get::AutomaticRemove=false']
HARD_PROTECTED = {'apt', 'dpkg', 'python3', 'python3-minimal', 'python3-gi', 'python3-cairo',
                  'gir1.2-gtk-3.0', 'libgtk-3-0t64', 'systemd', 'systemd-sysv', 'sudo', 'polkitd', 'pkexec'}
# Ignore caller environment, including APT_CONFIG, PYTHONPATH and dynamic loaders.
ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'HOME': '/root', 'LANG': 'C', 'LC_ALL': 'C', 'TERM': 'dumb'}


def require(condition):
    if not condition:
        raise ValueError('请求参数或软件包状态不符合要求，请重新检查。')


def matches(pattern, text):
    return len(text) <= 256 and re.fullmatch(pattern, text) is not None


def package(text):
    require(matches(r'[a-z0-9][a-z0-9+.-]*(?::[a-z0-9]+)?', text))


def snap(text):
    require(matches(r'[a-z0-9][a-z0-9-]*(?:_[a-z0-9]+)?', text))


def flatpak(text, ref=False):
    pattern = r'app/[A-Za-z0-9_][A-Za-z0-9_.-]*/[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+' if ref else r'[A-Za-z0-9_][A-Za-z0-9_.-]*'
    require(matches(pattern, text))


def command(request):
    require(bool(request))
    action, *args = request
    if action == 'apt-refresh' and not args:
        return [APT, *APT_OPTIONS, '-o', 'APT::Update::Error-Mode=any', '-o', 'Acquire::Retries=2', 'update']
    if action == 'apt-upgrade' and len(args) == 2:
        name, version = args
        package(name)
        require(matches(r'[0-9][A-Za-z0-9.+:~\-]*', version))
        return [APT, *APT_OPTIONS, '-y', '--no-remove', '--only-upgrade', 'install', '--', f'{name}={version}']
    if action == 'apt-remove' and len(args) == 1:
        package(args[0])
        require(args[0].split(':')[0] not in HARD_PROTECTED)
        return [APT, *APT_OPTIONS, '-y', 'remove', '--', args[0]]
    if action == 'snap-upgrade' and len(args) == 2:
        snap(args[0])
        require(matches(r'[0-9]+', args[1]))
        return ['/usr/bin/snap', 'refresh', args[0], f'--revision={args[1]}']
    if action == 'snap-remove' and len(args) == 1:
        snap(args[0])
        return ['/usr/bin/snap', 'remove', args[0]]
    if action == 'flatpak-upgrade' and len(args) == 2:
        flatpak(args[0], ref=True)
        require(matches(r'[0-9a-f]{64}', args[1]))
        return ['/usr/bin/flatpak', 'update', '--system', '--app', '--noninteractive', f'--commit={args[1]}', args[0]]
    if action == 'flatpak-remove' and len(args) == 1:
        flatpak(args[0])
        return ['/usr/bin/flatpak', 'uninstall', '--system', '--noninteractive', args[0]]
    raise ValueError('不支持的软件管理操作。')


def query(args):
    return subprocess.check_output(args, env=ENV, text=True, timeout=90, stdin=subprocess.DEVNULL)


def validate_state(request, args):
    action = request[0]
    if action in ('apt-upgrade', 'apt-remove'):
        name = request[1]
        require(query(['/usr/bin/dpkg-query', '-W', '-f=${db:Status-Status}', name]).strip() == 'installed')
        if action == 'apt-upgrade':
            held = query(['/usr/bin/apt-mark', 'showhold']).splitlines()
            require(name.split(':')[0] not in {p.split(':')[0] for p in held})
            policy = query(['/usr/bin/apt-cache', 'policy', '--', name])
            candidate = re.search(r'^\s*Candidate:\s*(\S+)\s*$', policy, re.M)
            require(candidate is not None and candidate[1] == request[2])
        simulated = query([args[0], '-s', *args[1:]])
        if action == 'apt-upgrade':
            require(not any(line.startswith(('Remv ', 'Purg ')) for line in simulated.splitlines()))
        else:
            removed = [line.split()[1] for line in simulated.splitlines() if line.startswith(('Remv ', 'Purg '))]
            require(name.split(':')[0] in {p.split(':')[0] for p in removed})
            for target in removed:
                package(target)
                require(target.split(':')[0] not in HARD_PROTECTED)
                flags = query(['/usr/bin/dpkg-query', '-W', '-f=${Essential}\t${Priority}', target]).strip().split('\t')
                require('yes' not in flags and 'required' not in flags)


def main(request):
    try:
        require(os.geteuid() == 0)
        args = command(request)
        print('XINGXU:running', flush=True)
        validate_state(request, args)
        # exec preserves the PTY/status stream and lets the package manager own
        # its locks and exit status. No privileged child is left behind.
        os.execve(args[0], args, ENV)
    except (ValueError, OSError, subprocess.SubprocessError, AttributeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
