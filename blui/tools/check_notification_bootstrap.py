# SPDX-License-Identifier: GPL-2.0-or-later
"""ROOT-RUN ONLY: read-only actual Explorer UIA/COM bootstrap diagnostic.

Creates no shell listener, TaskbarCreated broadcast, notification icon, helper
window, mouse/keyboard input or taskbar visibility changes. Never invokes an icon.
"""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/modules'))
from blui_desktop import native_windows, notification_history, notification_host, notification_system, notification_wire


def main():
    host = notification_host.Host(private=True)
    bridge = None
    try:
        source = host._find_explorer()
        if source is None:
            raise RuntimeError('Verified Windows Explorer notification provider unavailable')
        bridge = notification_history.Bridge(host._find_explorer,
            lambda handle: native_windows._identity(host.user, handle))
        rows, status = bridge.refresh()
        value = {'enabled': True, 'error': '', 'revision': bridge.revision,
            'host_handle': str(source[0]), 'icons': rows, 'platform': notification_system.build_number(),
            'controls': [], 'bootstrap': status}
        metadata, pixels = notification_wire.validate_snapshot(value)
        print(json.dumps({'platform': value['platform'], 'bootstrap': status,
            'icon_count': len(rows), 'pixel_count': len(pixels),
            'metadata_diagnostics': bridge.metadata.diagnostics if bridge.metadata else {},
            'metadata_path_forms': bridge.metadata.path_forms if bridge.metadata else {},
            'icons': [{'key': row['key'], 'tip': row['tip'], 'backend': row['backend'],
                       'actions': row['actions'], 'has_pixels': bool(row['cache_key'])}
                      for row in metadata['icons']]}, ensure_ascii=False, indent=2), flush=True)
        # Unsupported providers are a diagnostic result, not false success.
        return 0 if rows else 2
    finally:
        if bridge:
            bridge.close()
        host.close()


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='strict')
    raise SystemExit(main())
