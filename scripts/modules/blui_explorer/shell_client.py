# SPDX-License-Identifier: GPL-2.0-or-later
"""Isolated Shell client. No extension DLLs or persistent Python threads in BLUI."""
import atexit
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from . import mailbox

_retired = []


def reap():
    _retired[:] = [process for process in _retired if process.poll() is None]


def python_executable():
    if os.path.basename(sys.executable).lower() in {"python.exe", "python3", "python"}:
        return sys.executable
    path = os.path.join(sys.prefix, "bin", "python.exe")
    if not os.path.isfile(path):
        raise RuntimeError("BLUI's bundled Python is missing: " + path)
    return path


class Session:
    def __init__(self, paths, *, executable=None, worker=None, timeout=8.0, action="list"):
        reap()
        self.token = uuid.uuid4().hex
        self.paths = tuple(os.path.normpath(p) for p in paths)
        self.action = action
        self.items, self.errors, self.pending = {}, {}, {}
        self.last_used = time.monotonic()
        self.timeout, self.serial, self.invoked = timeout, 0, False
        self.directory = tempfile.mkdtemp(prefix="blui_shell_")
        try:
            self.process = subprocess.Popen(
                [executable or python_executable(), "-I", "-u",
                 worker or os.path.join(os.path.dirname(__file__), "shell_worker.py"), self.directory],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.request(action, paths=list(self.paths))
        except Exception:
            shutil.rmtree(self.directory, ignore_errors=True)
            raise

    def request(self, op, **payload):
        node = payload.get("node", "root") if op in {"list", "expand"} else "invoke"
        if any(p[0] == node for p in self.pending.values()):
            return
        if self.process.poll() is not None:
            self.errors[node] = "Windows menu helper exited. Retry to load a new session."
            return
        self.last_used = time.monotonic()
        if op == 'invoke':
            self.invoked = True
        self.serial += 1
        self.pending[self.serial] = (node, self.last_used, op)
        mailbox.publish(self.directory, "request-%d.json" % self.serial, dict(op=op, **payload))

    def poll(self):
        reap()
        changed = False
        for serial, (node, started, op) in list(self.pending.items()):
            reply = mailbox.take(self.directory, "reply-%d.json" % serial)
            if reply is not None:
                del self.pending[serial]
                if reply.get("ok"):
                    if op in {"list", "expand"}:
                        self.items[node] = reply["items"]
                    else:
                        self.items["invoke"] = True
                    self.errors.pop(node, None)
                else:
                    self.errors[node] = reply.get("error", "Windows menu failed")
                changed = True
                continue
            if self.process.poll() is not None:
                self.errors[node] = "Windows menu helper crashed or exited."
                del self.pending[serial]
                changed = True
                continue
            limit = self.timeout if op in {"list", "expand"} else 120.0
            if time.monotonic() - started > limit:
                self.errors[node] = (
                    "System command timed out; its result is unknown. Check files before retrying."
                    if op not in {"list", "expand"} else "Windows menu timed out. BLUI is still available.")
                self.close()
                changed = True
                break
        return changed

    def close(self):
        if self.process.poll() is None:
            self.process.kill()
            _retired.append(self.process)
        self.pending.clear()
        shutil.rmtree(self.directory, ignore_errors=True)


sessions = {}


def get_session(paths, retry=False):
    key = tuple(os.path.normpath(p) for p in paths)
    for session in list(sessions.values()):
        if session.paths == key and session.action == "list" and not retry and not session.invoked:
            session.last_used = time.monotonic()
            return session
        if session.paths == key and session.action == "list" and retry and not session.invoked:
            session.close()
            del sessions[session.token]
    # A small bound on helpers, while leaving an invoked extension's dialog alive.
    disposable = [s for s in sessions.values() if not s.invoked and "invoke" not in s.items and
                  not any(p[2] == "invoke" for p in s.pending.values())]
    while len(disposable) >= 3:
        old = min(disposable, key=lambda s: s.last_used)
        old.close()
        sessions.pop(old.token, None)
        disposable.remove(old)
    if len(sessions) >= 8:
        raise RuntimeError("Close existing Windows extension dialogs before opening another menu")
    session = Session(paths)
    sessions[session.token] = session
    return session


def close_all():
    for session in sessions.values():
        session.close()
    sessions.clear()


atexit.register(close_all)
