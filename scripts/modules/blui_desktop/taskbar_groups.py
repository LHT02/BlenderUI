# SPDX-License-Identifier: GPL-2.0-or-later
"""Pure application identity, stable task grouping and monitor geometry."""
import hashlib
import ntpath
from .taskbar_metrics import BAR_HEIGHT

MAX_TASKS = 256
BROKERS = frozenset(('applicationframehost.exe', 'shellexperiencehost.exe'))


def executable_path(value):
    return (isinstance(value, str) and 0 < len(value) <= 32768 and '\x00' not in value
            and ntpath.isabs(value) and bool(ntpath.splitdrive(value)[0])
            and ntpath.basename(value).casefold().endswith('.exe'))


def identity_key(row):
    app_id = row.get('app_id', '')
    executable = row.get('executable', '')
    if isinstance(app_id, str) and 0 < len(app_id) <= 512 and '\x00' not in app_id:
        value = 'app:' + app_id.casefold()
    elif executable_path(executable) and ntpath.basename(executable).casefold() not in BROKERS:
        value = 'exe:' + ntpath.normcase(ntpath.normpath(executable))
    else:
        # Do not guess application identity from a localized/window-controlled
        # title. Inaccessible/broker windows remain independently selectable.
        value = 'window:' + ':'.join(str(row.get(key, '')) for key in
            ('pid', 'process_started', 'thread_id', 'window_class', 'handle'))
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def groups(tasks, *, monitor='', all_monitors=True, excluded=()):
    if not isinstance(tasks, (list, tuple)) or len(tasks) > MAX_TASKS:
        raise ValueError('Invalid taskbar task list')
    result, lookup = [], {}
    excluded = {str(handle) for handle in excluded}
    for task in tasks:
        if not isinstance(task, dict) or task.get('handle') in excluded:
            continue
        if not all_monitors and monitor and task.get('monitor') not in ('', monitor):
            continue
        key = identity_key(task)
        if key not in lookup:
            executable = task.get('executable', '')
            name = (ntpath.splitext(ntpath.basename(executable))[0] if executable_path(executable)
                    else task.get('title', '') or task.get('window_class', 'Application'))
            group = {'key': key, 'title': name, 'executable': executable,
                     'app_id': task.get('app_id', ''), 'tasks': [], 'active': False}
            lookup[key] = group
            result.append(group)
        group = lookup[key]
        group['tasks'].append(dict(task))
        group['active'] = group['active'] or bool(task.get('active'))
    return result


def can_launch(row):
    return (row.get('actionable') is True and executable_path(row.get('executable'))
            and ntpath.basename(row['executable']).casefold() not in BROKERS
            and not row.get('app_id'))


def bar_rect(display, height=BAR_HEIGHT, *, system_hidden=False):
    rect, dpi = display['rect' if system_hidden else 'work'], display['dpi']
    pixels = max(24, min(rect[3] - rect[1], round(height * dpi[1] / 96)))
    return [rect[0], rect[3] - pixels, rect[2], rect[3]]


def menu_rect(display, anchor, width, height):
    work, dpi = display['work'], display['dpi']
    width = max(1, min(work[2] - work[0], round(width * dpi[0] / 96)))
    height = max(1, min(work[3] - work[1], round(height * dpi[1] / 96)))
    left = min(max(anchor[0], work[0]), work[2] - width)
    top = min(max(anchor[1] - height, work[1]), work[3] - height)
    return [left, top, left + width, top + height]
