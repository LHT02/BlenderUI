# SPDX-License-Identifier: GPL-2.0-or-later
"""One bounded desktop task per isolated process, with an explicit operation allowlist."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from blui_desktop import background, boards, file_services, icons, model, monitors, native_windows, weather
from blui_explorer import mailbox, worker_lifetime


def main():
    worker_lifetime.start()
    directory = sys.argv[1]
    try:
        request = None
        for _ in range(50):
            request = mailbox.take(directory, 'request.json')
            if request is not None:
                break
            time.sleep(.02)
        if not request:
            raise RuntimeError('Desktop request unavailable')
        if not isinstance(request, dict):
            raise ValueError('Invalid desktop request')
        action, args = request.get('action'), request.get('args')
        arity = {'scan': 1, 'paths': 1, 'save': 2, 'load': 1, 'tasks': 0, 'open': 1,
                 'board_save': 2, 'board_load': 1, 'monitors': 0, 'weather': 1, 'icons': 1,
                 'background': 1, 'recycle': 1, 'previews': 1, 'task_launch': 1,
                 'start_index': 1, 'start_state': 2, 'start_launch': 1, 'start_system': 1,
                 'start_location': 1, 'taskbar_settings_load': 1, 'taskbar_settings_save': 2}
        if action not in arity or not isinstance(args, list) or len(args) != arity[action]:
            raise ValueError('Unsupported desktop request')
        if action == 'scan':
            result = model.scan(*args)
        elif action == 'paths':
            result = model.inspect_paths(*args)
        elif action == 'save':
            result = model.save(*args)
        elif action == 'load':
            result = model.load(*args)
        elif action == 'tasks':
            result = native_windows.tasks()
        elif action == 'board_save':
            result = boards.save(*args)
        elif action == 'board_load':
            result = boards.load(*args)
        elif action == 'monitors':
            result = monitors.snapshot()
        elif action == 'icons':
            result = icons.extract(*args)
        elif action == 'previews':
            from blui_desktop import thumbnails
            result = thumbnails.extract(*args)
        elif action == 'task_launch':
            result = native_windows.launch(*args)
        elif action.startswith('taskbar_settings_'):
            from blui_desktop import taskbar_settings
            result = getattr(taskbar_settings, action.removeprefix('taskbar_settings_'))(*args)
        elif action.startswith('start_'):
            from blui_desktop import start_menu_backend
            result = getattr(start_menu_backend, action)(*args)
        elif action == 'background':
            result = background.inspect(*args)
        elif action == 'recycle':
            file_services.recycle(*args)
            result = True
        elif action == 'weather':
            if not isinstance(args[0], dict) or set(args[0]) != {'latitude', 'longitude', 'cache_directory', 'source', 'force'}:
                raise ValueError('Invalid weather request')
            result = weather.refresh(**args[0])
        elif action == 'open':
            path = args[0]
            if (os.name != 'nt' or not isinstance(path, str) or not path or
                len(path) > 32768 or '\x00' in path):
                raise ValueError('Invalid desktop open path')
            # User clicked a specific card. ShellExecute via startfile, never a command shell.
            os.startfile(os.path.abspath(path))
            result = True
        else:
            raise ValueError('Unsupported desktop request')
        reply = {'ok': True, 'value': result}
    except Exception as exc:
        reply = {'ok': False, 'error': str(exc)}
    mailbox.publish(directory, 'result.json', reply)


if __name__ == '__main__':
    main()
