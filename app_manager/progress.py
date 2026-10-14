"""Live package-manager output; percentages always belong to a named phase."""
from dataclasses import dataclass
import codecs
import errno
import os
import pty
import re
import selectors
import signal
import subprocess
import time


@dataclass(frozen=True)
class Progress:
    stage: str
    fraction: float | None = None


ANSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07]*(?:\x07|\x1b\\)')


class Parser:
    def __init__(self, callback):
        self.callback = callback
        self.stage = '正在处理更新'
        self.last = None

    def __call__(self, raw):
        line = ANSI.sub('', raw).strip()
        if not line:
            return
        event = None
        if line == 'XINGXU:running':
            event = Progress('授权已完成，正在准备操作')
        elif line.startswith(('dlstatus:', 'pmstatus:')):
            # A Debian package name may itself contain an architecture colon.
            match = re.match(r'^(dlstatus|pmstatus):.+?:(\d+(?:\.\d+)?):', line)
            if match:
                percent = float(match[2])
                if 0 <= percent <= 100:
                    event = Progress('正在下载软件包' if match[1] == 'dlstatus' else '正在安装和配置', percent / 100)
        else:
            lower = line.lower()
            if any(word in lower for word in ('download', 'get:', 'fetch', 'hit:')):
                self.stage = '正在下载'
            elif any(word in lower for word in ('unpack', 'install', 'setting up', 'configur', 'processing triggers')):
                self.stage = '正在安装和配置'
            elif any(word in lower for word in ('verify', 'verif', 'check', 'reading package')):
                self.stage = '正在检查软件包'
            # Flatpak/Snap terminal percentages. Do not label logs as overall progress.
            percent = re.search(r'(?<![\d.])(\d{1,3}(?:\.\d+)?)\s*%', line)
            if percent and 0 <= float(percent[1]) <= 100:
                event = Progress(self.stage, float(percent[1]) / 100)
            elif self.stage != '正在处理更新':
                event = Progress(self.stage)
        if event is not None and event != self.last:
            self.last = event
            self.callback(event)


def stream(args, env, callback, timeout):
    """Use an output-only terminal for Snap/Flatpak's live progress as well.

    Drain partial UTF-8, CR redraws and both output streams without waiting for
    process completion. Retain only a bounded diagnostic tail.
    """
    master, slave = pty.openpty()
    process = None
    selector = selectors.DefaultSelector()
    decoder = codecs.getincrementaldecoder('utf-8')('replace')
    pending = ''
    output = ''
    deadline = time.monotonic() + timeout
    timed_out = False
    parser = Parser(callback)
    try:
        process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=slave, stderr=slave,
                                   env={**env, 'TERM': 'dumb'}, start_new_session=True)
        os.close(slave)
        slave = None
        selector.register(master, selectors.EVENT_READ)
        eof = False
        while not eof:
            if not timed_out and time.monotonic() > deadline:
                # Never leave a privileged APT running while the UI releases its
                # operation lock. If it cannot be signalled, keep observing it.
                timed_out = True
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except PermissionError:
                    callback(Progress('操作耗时较长，仍在等待系统完成；请勿关闭窗口'))
            for _, _ in selector.select(.2):
                try:
                    chunk = os.read(master, 8192)
                except OSError as exc:
                    if exc.errno != errno.EIO:
                        raise
                    chunk = b''
                if not chunk:
                    eof = True
                    break
                text = decoder.decode(chunk)
                output = (output + text)[-65536:]
                pending += text
                lines = re.split(r'[\r\n]', pending)
                pending = lines.pop()[-8192:]
                for line in lines:
                    parser(line)
            if process.poll() is not None and not selector.select(0):
                eof = True
        if pending:
            parser(pending + decoder.decode(b'', final=True))
        status = process.wait()
        if timed_out and status != 0:
            raise subprocess.TimeoutExpired(args, timeout, output=output)
        return status, output
    finally:
        selector.close()
        os.close(master)
        if slave is not None:
            os.close(slave)
        if process is not None and process.poll() is None:
            # A callback/reader error must not release the caller's operation
            # lock with a package manager still running.
            process.wait()
