# SPDX-License-Identifier: GPL-2.0-or-later
"""Filesystem work shared by operators and tests. Never imports bpy.

Transfers refuse overwrites and self/descendant destinations. Archives are
published only when complete. A failed cross-volume move retains its source.
"""

import os
from pathlib import Path, PureWindowsPath
import shutil
import stat
import subprocess
import tempfile
import zipfile


def valid_name(name):
    if not name or name in {".", ".."} or name.endswith((" ", ".")):
        raise ValueError("Enter a valid file name")
    if any(ch in '<>:"/\\|?*' or ord(ch) < 32 for ch in name) or PureWindowsPath(name).is_reserved():
        raise ValueError("This name is not supported by Windows")
    return name


def canonical(path):
    return os.path.normcase(os.path.realpath(path))


def transfer(paths, directory, move=False):
    destination = Path(directory)
    if not destination.is_dir():
        raise ValueError("Destination folder does not exist")
    plan = []
    used = set()
    for item in paths:
        source = Path(item)
        target = destination / source.name
        src, dst = canonical(source), canonical(target)
        if src == dst or (source.is_dir() and Path(dst).is_relative_to(Path(src))):
            raise ValueError("Cannot place a folder inside itself: " + source.name)
        if target.exists() or target.is_symlink() or dst in used:
            raise FileExistsError("Already exists (nothing overwritten): " + str(target))
        if not source.exists():
            raise FileNotFoundError(str(source))
        used.add(dst)
        plan.append((source, target))
    completed = []
    for source, target in plan:
        try:
            if move and os.stat(source).st_dev == os.stat(destination).st_dev:
                os.rename(source, target)
            else:
                if source.is_dir():
                    shutil.copytree(source, target, symlinks=True)
                else:
                    # Exclusive creation makes a concurrent destination collision safe.
                    with source.open("rb") as src, target.open("xb") as dst:
                        shutil.copyfileobj(src, dst, 1024 * 1024)
                    shutil.copystat(source, target)
                if move:
                    if source.is_dir():
                        shutil.rmtree(source)
                    else:
                        source.unlink()
            completed.append(str(target))
        except OSError as exc:
            raise OSError("%d item(s) completed; failed on %s: %s" %
                          (len(completed), source.name, exc)) from exc
    return completed


def seven_zip():
    candidates = [shutil.which("7z"), os.path.join(os.environ.get("ProgramFiles", ""), "7-Zip", "7z.exe")]
    return next((p for p in candidates if p and os.path.isfile(p)), None)


def archive(paths, output, kind="ZIP"):
    target = Path(output)
    if target.exists():
        raise FileExistsError("Archive already exists: " + str(target))
    parent = Path(paths[0]).parent
    if any(Path(p).parent != parent for p in paths):
        raise ValueError("Select items from the same folder")
    # Stage outside the input trees, so an archive can never include itself.
    with tempfile.TemporaryDirectory(prefix="blui_archive_") as staging:
        staged = Path(staging) / ("archive.7z" if kind == "7Z" else "archive.zip")
        if kind == "7Z":
            exe = seven_zip()
            if not exe:
                raise RuntimeError("Install 7-Zip to create 7Z archives")
            result = subprocess.run([exe, "a", "-t7z", str(staged), "--"] +
                                    [Path(p).name for p in paths], cwd=parent,
                                    capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if result.returncode != 0:
                raise OSError("7-Zip failed: " + result.stderr.decode(errors="replace")[-500:])
        else:
            with zipfile.ZipFile(staged, "w", zipfile.ZIP_DEFLATED) as result:
                for value in paths:
                    source = Path(value)
                    entries = [source]
                    if source.is_dir():
                        entries.extend(source.rglob("*"))
                    for entry in entries:
                        if entry.is_symlink():
                            raise ValueError("Archive links separately: " + str(entry))
                        result.write(entry, entry.relative_to(parent))
        with staged.open("rb") as src, target.open("xb") as dst:
            shutil.copyfileobj(src, dst, 1024 * 1024)
    return str(target)


def extract_zip(source, destination):
    target = Path(destination)
    if target.exists():
        raise FileExistsError("Destination already exists: " + str(target))
    with zipfile.ZipFile(source) as archive_file:
        for entry in archive_file.infolist():
            path = PureWindowsPath(entry.filename)
            if path.is_absolute() or path.drive or ".." in path.parts or any(":" in p for p in path.parts):
                raise ValueError("Unsafe archive path: " + entry.filename)
            if stat.S_ISLNK(entry.external_attr >> 16):
                raise ValueError("Archive contains a symbolic link")
        target.mkdir()  # Exclusive: never merge into an existing tree.
        archive_file.extractall(target)
    return str(target)
