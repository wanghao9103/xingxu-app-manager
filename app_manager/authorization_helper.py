#!/usr/bin/python3 -I
"""One-time account authorization. This has its own always-authenticated action.

Never expose this operation through the password-free management helper.
"""
import json
import os
from pathlib import Path
import pwd
import re
import stat
import sys
import tempfile

RULES = Path('/etc/polkit-1/rules.d')
STATE = Path('/var/lib/miemie-app-manager/authorizations')
MANAGEMENT_HELPER = '/usr/libexec/miemie-app-manager-helper'


def account():
    value = os.environ.get('PKEXEC_UID', '')
    if os.geteuid() != 0 or not re.fullmatch(r'[1-9][0-9]{0,9}', value):
        raise ValueError('需要通过系统授权确认当前账号。')
    info = pwd.getpwuid(int(value))
    return info.pw_uid, info.pw_name


def trusted_directory(path):
    for item in (path, *path.parents):
        mode = item.lstat()
        if not stat.S_ISDIR(mode.st_mode) or mode.st_uid != 0 or mode.st_mode & 0o022:
            raise ValueError('授权目录权限不符合要求。')


def rule_text(username):
    # JSON string quoting also safely quotes a JavaScript string literal.
    user = json.dumps(username, ensure_ascii=True)
    program = json.dumps(MANAGEMENT_HELPER)
    return ('// Managed by Xingxu. Revoke through its authorization settings.\n'
            'polkit.addRule(function(action, subject) {\n'
            '  if (action.id === "io.miemie.AppManager.manage" &&\n'
            f'      action.lookup("program") === {program} &&\n'
            f'      subject.user === {user} && subject.local && subject.active) {{\n'
            '    return polkit.Result.YES;\n'
            '  }\n'
            '});\n')


def atomic_write(path, data):
    fd, temporary = tempfile.mkstemp(prefix='.xingxu-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as file:
            os.fchmod(file.fileno(), 0o644)
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def configure(operation, uid, username):
    if operation not in ('grant', 'revoke'):
        raise ValueError('不支持的授权设置。')
    os.umask(0o022)
    trusted_directory(RULES)
    # Create one directory at a time; never traverse an unexpected symlink.
    for directory in (STATE.parent, STATE):
        directory.mkdir(mode=0o755, exist_ok=True)
        trusted_directory(directory)
    rule = RULES / f'49-xingxu-app-manager-{uid}.rules'
    marker = STATE / f'{uid}.json'
    if operation == 'revoke':
        rule.unlink(missing_ok=True)
        marker.unlink(missing_ok=True)
        return
    previous = rule.read_bytes() if rule.is_file() else None
    atomic_write(rule, rule_text(username).encode())
    try:
        atomic_write(marker, json.dumps({'uid': uid, 'user': username, 'enabled': True}).encode())
    except OSError:
        if previous is None:
            rule.unlink(missing_ok=True)
        else:
            atomic_write(rule, previous)
        raise


def main(args):
    try:
        if len(args) != 1 or args[0] not in ('grant', 'revoke'):
            raise ValueError('只能启用或撤销当前账号的星序授权。')
        uid, username = account()
        configure(args[0], uid, username)
        print('星序长期授权已启用。' if args[0] == 'grant' else '星序长期授权已撤销。')
        return 0
    except (ValueError, KeyError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
