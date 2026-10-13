# SPDX-License-Identifier: GPL-2.0-or-later
"""Bounded Explorer notification-provider bootstrap, isolated from the NIM pump.

An opaque UIA token is tied to an Explorer process creation identity and RuntimeId.
Historical metadata without a UIA default-action provider is DISPLAY-only: neither
callback message nor notification version is present in ITrayNotify's NOTIFYITEM.
"""
import hashlib
import json
import queue
import threading
import time
from . import notification_uia_native as uia
from . import notification_system, notification_toolbar_native as toolbar_native

TRAY_CLASSES = {'TrayNotifyWnd', 'SystemTray.SystemTrayFrame'}
TRAY_IDS = {'NotificationAreaIcons', 'NotifyIconStack'}
EXCLUDED_IDS = {'ControlCenterButton', 'ShowDesktopStack', 'ClockButton', 'DateTimeButton',
                'InputIndicatorButton', 'NotificationCenterButton'}
SYSTEM_IDS = {'NETWORK': {'ControlCenterButton'}, 'VOLUME': {'ControlCenterButton'},
              'POWER': {'ControlCenterButton'}, 'INPUT': {'InputIndicatorButton', 'InputIndicatorIcon'},
              'NOTIFICATIONS': {'NotificationCenterButton'}, 'CALENDAR': {'ClockButton', 'DateTimeButton'}}
SYSTEM_CLASSES = {'INPUT': {'InputIndicator', 'TrayInputIndicatorWClass', 'SystemTray.LanguageTextIcon'},
                  'CALENDAR': {'TrayClockWClass'}}
APP_CLASSES = {'SystemTray.NotifyIcon', 'SystemTray.NotificationAreaIcon'}
MAX_NODES, MAX_DEPTH, MAX_ICONS = 384, 12, 128


def token(source, runtime):
    if (not isinstance(source, tuple) or len(source) != 2 or not isinstance(source[1], tuple) or
            len(source[1]) != 4 or not isinstance(runtime, tuple) or not 1 <= len(runtime) <= 32 or
            any(type(value) is not int for value in runtime)):
        raise ValueError('Invalid historical notification provider identity')
    payload = json.dumps((source, runtime), separators=(',', ':')).encode('utf-8')
    return 'uia:' + hashlib.sha256(payload).hexdigest()


def eligible(description, *, scoped, explorer_pid):
    """No localized-name matching; only controls inside an actual tray subtree."""
    return bool(scoped and description['pid'] == explorer_pid and description['enabled'] and
                description['type'] == 50000 and description['name'] and
                description['id'] not in EXCLUDED_IDS)


def row_for(source, description, pixels=(0, 0, ''), *, actionable=False):
    handle, identity = source
    return {'key': token(source, description['runtime']), 'handle': str(handle), 'uid': 0,
        'guid': '', 'callback': 0, 'version': 0, 'tip': description['name'], 'hidden': False,
        'width': pixels[0], 'height': pixels[1], 'rgba': pixels[2],
        'pid': identity[0], 'thread_id': identity[1], 'process_started': identity[2],
        'window_class': identity[3], 'backend': 'UIA', 'actions': ['LEFT'] if actionable else []}


def merge_rows(live, history):
    """Deduplicate only actual application HWND+uid/GUID, never ambiguous names."""
    keys = {row['key'] for row in live}
    result = list(live)
    for row in history:
        if row['key'] not in keys and len(result) < MAX_ICONS:
            result.append(row)
            keys.add(row['key'])
    return result


class Bridge:
    def __init__(self, find_source, identity, *, session_factory=uia.Session, metadata_factory=None, overflow_factory=None, pixel_fallback=None):
        self.find_source, self.identity = find_source, identity
        self.session = session_factory()
        if overflow_factory is None:
            from .notification_explorer_native import overflow_windows
            overflow_factory = overflow_windows
        self.find_overflow = overflow_factory
        if pixel_fallback is None:
            from .notification_toolbar_pixels import capture
            pixel_fallback = capture
        self.pixel_fallback = pixel_fallback
        self.metadata, self.metadata_error = None, ''
        if metadata_factory is None:
            from .notification_metadata_native import Metadata
            metadata_factory = Metadata
        try:
            self.metadata = metadata_factory(self.session, identity)
        except (OSError, ValueError, RuntimeError) as exc:
            self.metadata_error = str(exc)[:256]
        self.source, self.rows, self.revision = None, [], 0
        self.status = {'state': 'UNAVAILABLE', 'count': 0, 'error': ''}

    def _walk(self, source, target=None, system=None, event='LEFT'):
        root = self.session.element(source[0])
        pending, rows = [(root, 0, False, None, False, None)], []
        for container in self.find_overflow(source, self.identity):
            try:
                pending.append((self.session.element(container[0]), 0, True, None, False, container))
            except (OSError, ValueError):
                continue
        seen, visits, deadline = set(), 0, time.monotonic() + 2
        metadata = self.metadata.snapshot() if self.metadata else []
        by_name = {}
        for item in metadata:
            by_name.setdefault(item['tip'], []).append(item)
        try:
            while pending and visits < MAX_NODES and time.monotonic() < deadline:
                element, depth, scope, toolbar, app_scope, container = pending.pop(0)
                visits += 1
                try:
                    item = self.session.describe(element)
                    if item['pid'] != source[1][0] or item['runtime'] in seen:
                        continue
                    seen.add(item['runtime'])
                    scope = scope or item['class'] in TRAY_CLASSES or item['id'] in TRAY_IDS
                    app_scope = app_scope or (scope and (item['id'] in TRAY_IDS or item['class'] in APP_CLASSES))
                    if scope and item['class'] == 'ToolbarWindow32' and item.get('handle'):
                        owner = self.identity(item['handle'])
                        if owner and owner[0] == source[1][0] and owner[2] == source[1][2] and owner[3] == 'ToolbarWindow32':
                            toolbar = (item['handle'], owner)
                    is_system = bool(system and scope and item['enabled'] and item['type'] == 50000 and
                                     (item['id'] in SYSTEM_IDS.get(system, set()) or
                                      item['class'] in SYSTEM_CLASSES.get(system, set())))
                    if is_system:
                        pattern, slot = self.session.action_pattern(element)
                        try:
                            if pattern and self.identity(source[0]) == source[1] and self.session.runtime_id(element) == item['runtime']:
                                uia.checked(uia.call(pattern, slot, uia.HRESULT, []))
                                return rows, True
                        finally:
                            uia.release(pattern)
                    if eligible(item, scoped=scope and bool(toolbar or app_scope), explorer_pid=source[1][0]):
                        pattern, slot = self.session.action_pattern(element)
                        try:
                            pixels = by_name.get(item['name'], [])
                            matching = pixels[0] if len(pixels) == 1 else None
                            control = (notification_system.GUID_ACTIONS.get(matching['guid']) if matching and
                                       matching['identity'][0] == source[1][0] else None)
                            if control:
                                if system == control and self.identity(source[0]) == source[1]:
                                    if toolbar:
                                        toolbar_native.action(source, toolbar, item['rect'], 'LEFT', identity=self.identity, container=container)
                                        return rows, True
                                    if pattern:
                                        uia.checked(uia.call(pattern, slot, uia.HRESULT, []))
                                        return rows, True
                                continue  # Fixed system control already owns this icon.
                            # A unique same-label match may supply presentation
                            # pixels, never callback identity or action authority.
                            pixels = pixels[0]['pixels'] if len(pixels) == 1 else (0, 0, '')
                            if not pixels[0] and toolbar and not target and not system:
                                pixels = self.pixel_fallback(source, toolbar, item['rect'], self.identity, container=container)
                            row = row_for(source, item, pixels, actionable=bool(pattern))
                            if toolbar and notification_system.build_number() < 22000:
                                # Native toolbar click semantics are provided by
                                # Explorer, not a guessed app callback/version.
                                try:
                                    rect = item.get('rect', ())
                                    if len(rect) == 4 and 4 <= rect[2] - rect[0] <= 256 and 4 <= rect[3] - rect[1] <= 256:
                                        row['backend'], row['actions'] = 'TOOLBAR', sorted(toolbar_native.EVENTS)
                                        row['button_rect'] = list(rect)
                                        row['toolbar_handle'], row['toolbar_thread'] = str(toolbar[0]), toolbar[1][1]
                                        if container:
                                            row['overflow_handle'], row['overflow_thread'] = str(container[0]), container[1][1]
                                except (TypeError, ValueError):
                                    pass
                            if target == row['key']:
                                if self.identity(source[0]) != source[1]:
                                    raise ValueError('Historical notification provider changed')
                                if self.session.runtime_id(element) != item['runtime']:
                                    raise ValueError('Historical notification element changed')
                                previous = next((old for old in self.rows if old['key'] == target), None)
                                if previous is None or previous['tip'] != item['name']:
                                    raise ValueError('Historical notification button changed')
                                if row['backend'] == 'TOOLBAR':
                                    if any(previous.get(field) != row.get(field) for field in ('button_rect', 'toolbar_handle', 'toolbar_thread', 'overflow_handle', 'overflow_thread')):
                                        raise ValueError('Original notification button geometry or provider changed')
                                    toolbar_native.action(source, toolbar, item['rect'], event, identity=self.identity, container=container)
                                elif event == 'LEFT' and pattern:
                                    uia.checked(uia.call(pattern, slot, uia.HRESULT, []))
                                else:
                                    raise ValueError('Historical notification icon does not support this action')
                                return rows, True
                            rows.append(row)
                        finally:
                            uia.release(pattern)
                        if len(rows) >= MAX_ICONS:
                            break
                    if depth < MAX_DEPTH:
                        child = self.session.child(element)
                        try:
                            while child and child.value and len(pending) + visits < MAX_NODES:
                                sibling = self.session.child(child, sibling=True)
                                pending.append((child, depth + 1, scope, toolbar, app_scope, container))
                                child = sibling
                                if time.monotonic() >= deadline:
                                    break
                        finally:
                            uia.release(child)
                except (OSError, ValueError):
                    if target:
                        raise
                finally:
                    uia.release(element)
            return rows, False
        finally:
            for element, _depth, _scope, _toolbar, _app_scope, _container in pending:
                uia.release(element)

    def refresh(self):
        source = self.find_source()
        if not source or self.identity(source[0]) != source[1]:
            rows, error = [], 'Original Windows notification provider is unavailable'
        else:
            rows, _found = self._walk(source)
            error = '' if rows else 'Windows notification provider exposes no supported icon controls'
            # Preserve metadata-only icons if UIA has no matching control. These
            # are clearly DISPLAY-only and offer a restore-original-tray fallback.
            if self.metadata:
                names = {row['tip'] for row in rows}
                for item in self.metadata.snapshot():
                    if (item['guid'] in notification_system.GUID_ACTIONS and
                            item['identity'][0] == source[1][0]):
                        continue
                    if item['tip'] not in names and len(rows) < MAX_ICONS:
                        owner = item['identity']
                        rows.append({'key': 'guid:' + item['guid'] if item['guid'] else
                            'hwnd:%d:%d' % (item['handle'], item['uid']),
                            'handle': str(item['handle']), 'uid': item['uid'], 'guid': item['guid'],
                            'callback': 0, 'version': 0, 'tip': item['tip'], 'hidden': item['hidden'],
                            'width': item['pixels'][0], 'height': item['pixels'][1], 'rgba': item['pixels'][2],
                            'pid': owner[0], 'thread_id': owner[1], 'process_started': owner[2],
                            'window_class': owner[3], 'backend': 'OVERFLOW' if item['tip'] and
                                10240 <= notification_system.build_number() < 22000 else 'DISPLAY',
                            'actions': ['LEFT', 'RIGHT', 'DOUBLE'] if item['tip'] and
                                10240 <= notification_system.build_number() < 22000 else []})
        self.source = source
        if rows and any(row['backend'] in {'DISPLAY', 'OVERFLOW', 'UIA'} for row in rows) and not error:
            error = 'Some historical icons require the original Windows tray'
        status = {'state': 'READY' if rows and not error else 'PARTIAL' if rows else 'UNAVAILABLE',
                  'count': len(rows), 'error': error or self.metadata_error}
        if (rows, status) != (self.rows, self.status):
            self.revision += 1
        self.rows, self.status = rows, status
        return self.rows, self.status

    def action(self, key, event):
        deferred = next((row for row in self.rows if row['key'] == key and row['backend'] == 'OVERFLOW'), None)
        if deferred:
            return self._deferred(deferred, event)
        if not isinstance(key, str) or not isinstance(event, str) or event not in toolbar_native.EVENTS or not key.startswith('uia:'):
            raise ValueError('Historical icon only supports its provider default action; use original Windows tray for other actions')
        if not self.source or self.find_source() != self.source or self.identity(self.source[0]) != self.source[1]:
            self.rows = []
            raise ValueError('Original Windows notification provider restarted')
        if not any(row['key'] == key and event in row['actions'] for row in self.rows):
            raise ValueError('Historical notification icon changed or exited')
        fresh, _found = self._walk(self.source)
        candidate = next((row for row in fresh if row['key'] == key and event in row['actions']), None)
        if candidate and candidate['backend'] == 'TOOLBAR':
            rect = candidate['button_rect']
            x, y = (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2
            for other in fresh:
                bounds = other.get('button_rect')
                if (other['key'] != key and other.get('toolbar_handle') == candidate['toolbar_handle'] and bounds and
                        bounds[0] <= x < bounds[2] and bounds[1] <= y < bounds[3]):
                    raise ValueError('Ambiguous notification toolbar hit rectangle')
        _rows, found = self._walk(self.source, target=key, event=event)
        if not found:
            raise ValueError('Historical notification icon is no longer available')

    def _deferred(self, row, event):
        from . import notification_explorer_native as explorer
        if event not in {'LEFT', 'RIGHT', 'DOUBLE'} or not row['tip'] or not self.metadata:
            raise ValueError('This historical icon needs the original Windows notification area')
        source = self.find_source()
        expected = (row['pid'], row['thread_id'], row['process_started'], row['window_class'])
        if not source or source != self.source or self.identity(int(row['handle'])) != expected:
            raise ValueError('Historical notification application changed or exited')
        def original():
            matches = [item for item in self.metadata.snapshot() if item['handle'] == int(row['handle']) and
                       item['uid'] == row['uid'] and item['guid'] == row['guid'] and item['identity'] == expected and
                       item['tip'] == row['tip']]
            return len(matches) == 1
        if not original():
            raise ValueError('Historical notification metadata changed')
        state = explorer.open_overflow(source, self.session, self.identity)
        state['action'] = event
        try:
            fresh, _found = self._walk(source)
            candidates = [item for item in fresh if item['tip'] == row['tip'] and event in item['actions'] and
                          item['backend'] == 'TOOLBAR']
            if len(candidates) != 1 or not original() or self.identity(int(row['handle'])) != expected:
                raise ValueError('Historical icon cannot be uniquely located; use Original Windows Notification Area')
            old_rows = self.rows
            try:
                self.rows = fresh
                self.action(candidates[0]['key'], event)
            finally:
                self.rows = old_rows
        finally:
            explorer.close_overflow(source, self.session, self.identity, state)

    def system(self, key, event):
        from . import notification_system, notification_system_native
        notification_system.request(key, event, notification_system.build_number())
        if event == 'LEFT' and key in SYSTEM_IDS:
            source = self.find_source()
            if source and self.identity(source[0]) == source[1]:
                try:
                    _rows, found = self._walk(source, system=key)
                    if found:
                        return
                except (OSError, ValueError):
                    pass  # Fixed public shortcut/settings fallback, not fake success.
        notification_system_native.action(key, event)

    def close(self):
        try:
            if self.metadata:
                self.metadata.close()
        finally:
            self.session.close()


class Service:
    """The host's message pump only consumes RAM; slow COM stays on this thread."""
    def __init__(self, find_source, identity):
        self.requests, self.updates = queue.Queue(maxsize=16), queue.Queue(maxsize=2)
        self.stop = threading.Event()
        self.rows = []
        self.status = {'state': 'LOADING', 'count': 0, 'error': ''}
        self.revision = 0
        self.thread = threading.Thread(target=self._run, args=(find_source, identity),
                                       name='BLUI historical notification provider', daemon=True)
        self.thread.start()

    def _publish(self, rows, status, error=''):
        value = (rows, status, error)
        try:
            self.updates.put_nowait(value)
        except queue.Full:
            try:
                self.updates.get_nowait()
                self.updates.put_nowait(value)
            except (queue.Full, queue.Empty):
                pass

    def _run(self, find_source, identity):
        bridge = None
        try:
            bridge = Bridge(find_source, identity)
            next_refresh = 0
            while not self.stop.is_set():
                now = time.monotonic()
                if now >= next_refresh:
                    self._publish(*bridge.refresh())
                    next_refresh = time.monotonic() + 5
                try:
                    key, event = self.requests.get(timeout=.1)
                    if key.startswith('system:'):
                        bridge.system(key[7:], event)
                    else:
                        bridge.action(key, event)
                    next_refresh = 0
                except queue.Empty:
                    continue
                except (OSError, ValueError, RuntimeError) as exc:
                    self._publish(bridge.rows, bridge.status, str(exc)[:1024])
        except (OSError, ValueError, RuntimeError) as exc:
            self._publish([], {'state': 'UNAVAILABLE', 'count': 0, 'error': str(exc)[:256]})
        finally:
            if bridge:
                bridge.close()

    def poll(self):
        error = ''
        while True:
            try:
                rows, status, error = self.updates.get_nowait()
            except queue.Empty:
                return error
            if (rows, status) != (self.rows, self.status):
                self.revision += 1
            self.rows, self.status = rows, status

    def action(self, key, event):
        if (not self.thread.is_alive() or not isinstance(event, str) or event not in toolbar_native.EVENTS or
                not any(row['key'] == key and event in row['actions'] for row in self.rows)):
            raise ValueError('Historical icon does not support this action; use original Windows notification area')
        try:
            self.requests.put_nowait((key, event))
        except queue.Full:
            raise ValueError('Windows notification provider is busy') from None

    def system(self, key, event):
        from . import notification_system
        notification_system.request(key, event, notification_system.build_number())
        try:
            self.requests.put_nowait(('system:' + key, event))
        except queue.Full:
            raise ValueError('Windows notification provider is busy') from None

    def close(self):
        self.stop.set()
