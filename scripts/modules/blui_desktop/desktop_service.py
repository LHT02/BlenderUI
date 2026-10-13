# SPDX-License-Identifier: GPL-2.0-or-later
"""Explicit desktop replacement orchestration. Retains tokens, never Window/Area/Tree RNA."""
import os

from . import desktop_host, monitors


class RNAWindows:
    """Main-thread adapter; native parenting/file I/O belongs to desktop_host helpers."""
    def fresh(self, token):
        import bpy
        return next((window for window in bpy.context.window_manager.windows
                     if window.blui_shell_role == 'DESKTOP' and window.blui_native_handle != '0' and
                     (window.as_pointer(), window.blui_native_handle) == token), None)

    def alive(self, token):
        return self.fresh(token) is not None

    def busy(self):
        import bpy
        manager = bpy.context.window_manager
        if getattr(manager, 'blui_has_path_drag', False):
            return True
        # Lifecycle only. Keep runtime's conservative Node/thumbnail/session gate unchanged.
        # An older binary fails closed using its original strict read-only getter.
        return any(getattr(window, 'blui_has_desktop_interaction',
                           getattr(window, 'blui_has_modal_interaction', True))
                   for window in manager.windows)

    def ready(self):
        from . import runtime, session
        if session.disable_for_tests or session._loaded:
            return True
        try:
            session.begin(runtime)
        except RuntimeError:
            return False
        return False  # Never create empty per-monitor trees before profile restore finishes.

    def directory(self):
        from . import session
        return session.storage_directory()

    def refresh_monitors(self):
        from . import runtime
        runtime._last_monitors = 0.0  # Request the existing isolated monitor job, not Win32 here.

    def create(self, display):
        import bpy
        context = bpy.context
        source = next((window for window in context.window_manager.windows
                       if window.blui_shell_role == 'NORMAL' and window.blui_native_handle != '0'), None)
        if source is None:
            source = next((window for window in context.window_manager.windows
                           if window.blui_native_handle != '0'), None)
        if source is None:
            raise RuntimeError('Could not open a desktop window')
        before = {window.as_pointer() for window in context.window_manager.windows}
        with context.temp_override(window=source):
            result = bpy.ops.wm.blui_shell_window_create(role='DESKTOP',
                width=max(200, min(16384, display['work'][2] - display['work'][0])),
                height=max(120, min(16384, display['work'][3] - display['work'][1])))
        created = [window for window in context.window_manager.windows if window.as_pointer() not in before]
        if result != {'FINISHED'} or len(created) != 1 or created[0].blui_shell_role != 'DESKTOP':
            raise RuntimeError('Could not open a desktop window')
        return created[0].as_pointer(), created[0].blui_native_handle

    def configure(self, token, display):
        import bpy
        from . import model, paths, session
        from bl_operators.blui_desktop import _initialize
        window = self.fresh(token)
        if window is None:
            raise RuntimeError('A desktop canvas was removed; reconnect the desktop canvases')
        area = max(window.screen.areas, key=lambda area: area.width * area.height)
        tree = next((tree for tree in session.roots() if tree.monitor == display['device']), None)
        if tree is None and display['primary']:
            tree = next((tree for tree in session.roots() if not tree.monitor), None)
        deferred_scan = False
        if tree is None:
            area.type = 'NODE_EDITOR'
            region = next((region for region in area.regions if region.type == 'WINDOW'), None)
            with bpy.context.temp_override(window=window, area=area, region=region):
                try:
                    tree = _initialize(area, paths.desktop())
                except RuntimeError:
                    # _initialize assigns the complete tree before bounded job
                    # admission. A full eight-job queue must not orphan a window
                    # or create another empty tree next tick. Retry only its scan.
                    tree = area.spaces.active.node_tree
                    if not tree or tree.bl_idname != model.TREE or not tree.board_id:
                        raise
                    deferred_scan = True
            tree.board_name = display['device']
        area.type = 'NODE_EDITOR'
        space = area.spaces.active
        space.tree_type, space.node_tree, space.pin = model.TREE, tree, True
        space.show_region_ui = space.show_region_toolbar = False
        tree.monitor = display['device']
        return tree.board_id if deferred_scan else ''

    def scan(self, board_id):
        from . import runtime, session
        tree = session.by_id(board_id)
        if tree is None:
            return True
        try:
            runtime.submit('scan', tree, tree.directory)
            return True
        except RuntimeError:
            return False

    def close(self, token):
        import bpy
        window = self.fresh(token)
        if window is None:
            return
        with bpy.context.temp_override(window=window):
            result = bpy.ops.wm.window_close(force_close=True)
        if result != {'FINISHED'}:
            raise RuntimeError('Desktop canvas close is pending')

    def finish_save(self):
        from . import runtime, session
        if session.disable_for_tests or not session._loaded or not session.roots():
            return True, ''
        try:
            session.save_now(runtime)  # RAM snapshot + isolated job, never disk I/O here.
            scheduler = session._scheduler
            return (not scheduler.dirty and scheduler.job is None), scheduler.error
        except (OSError, RuntimeError, ValueError, ReferenceError) as exc:
            return True, str(exc)[:2048]  # Never block Windows restoration on storage failure.


class Service:
    def __init__(self, adapter=None, host=None):
        self.adapter, self.host = adapter or RNAWindows(), host or desktop_host
        self.desired = False
        self.phase = 'IDLE'
        self.owned = {}  # {(RNA pointer integer, native HWND string): display device string}
        self.serial = 0
        self.after_restore = 'DISABLE'
        self.connected_topology = ''
        self.fresh_after = None
        self.error = ''
        self.deferred_scans = set()
        self._status = self.host.snapshot()

    def enable(self):
        if os.name != 'nt':
            raise RuntimeError('Desktop replacement is available only on Windows')
        self.desired, self.error = True, ''
        self._begin_restore('BUILD', force_fresh=True)

    def restore(self, *, close_windows=True):
        self.desired, self.error = False, ''
        self._begin_restore('DISABLE' if close_windows else 'DETACH', force_fresh=False)

    def _begin_restore(self, after, *, force_fresh=False):
        self.after_restore, self.phase = after, 'RESTORING'
        if force_fresh:
            self.adapter.refresh_monitors()
            self.fresh_after = self._snapshot_id
        self.host.start(self.adapter.directory())
        self.serial = self.host.restore()

    @property
    def _snapshot_id(self):
        return getattr(self, '_seen_snapshot', None)

    def needs_service(self):
        return self.desired or bool(self.owned) or self.phase not in ('IDLE', 'DETACHED', 'ERROR')

    def snapshot(self):
        result = dict(self._status, handles=list(self._status.get('handles', [])))
        result.update(desired=self.desired, phase=self.phase, error=self.error or result.get('error', ''))
        if self.phase in ('RESTORING', 'BUILDING', 'CONNECTING', 'CLOSING'):
            result['state'] = 'Desktop Connection Pending' if self.desired else 'Desktop Recovery Pending'
        return result

    def _fail(self, exc):
        self.error = str(exc)[:2048]
        self.desired = False
        self.phase, self.after_restore = 'ERROR', 'DISABLE'
        # Restoration may be unavailable because an earlier recovery witness is
        # still alive. Never close sources based on an initial empty RAM status.
        try:
            self._begin_restore('DISABLE')
        except (OSError, RuntimeError, ValueError) as error:
            self.error = str(error)[:2048]
            self.phase = 'ERROR'

    def tick(self, snapshot):
        self._seen_snapshot = id(snapshot)
        self._status = self.host.tick()  # RAM-only; keep an existing idle guard healthy without auto-start.
        if not self.needs_service():
            return
        self.owned = {token: device for token, device in self.owned.items() if self.adapter.alive(token)}
        try:
            if self.phase == 'SAVING':
                done, error = self.adapter.finish_save()
                if done or error:
                    self.phase = 'IDLE'
                    if error:
                        self.error = error
                return
            if self.phase == 'CLOSING':
                if not self._status.get('enabled') and not self._status.get('pending_restore'):
                    self.phase = 'IDLE'
                return
            if self.phase == 'ERROR':
                return  # Explicit Restore retries a failed guardian; no tight automatic relaunch.
            if self.phase == 'RESTORING':
                if self._status.get('error') and self._status.get('completed_serial', 0) < self.serial:
                    self.error, self.phase = self._status['error'], 'ERROR'
                    return
                if (self._status.get('completed_serial', 0) < self.serial or self._status.get('enabled') or
                        self._status.get('pending_restore')):
                    return
                if self.after_restore == 'DETACH':
                    self.phase = 'DETACHED'  # Undo restores Windows but does not close canvas RNA.
                    return
                if self.adapter.busy():
                    return
                if self.after_restore == 'DISABLE':
                    for token in tuple(self.owned):
                        self.adapter.close(token)
                        self.owned.pop(token, None)
                    self.deferred_scans.clear()
                    self.phase = 'SAVING'
                    done, error = self.adapter.finish_save()
                    if done or error:
                        self.phase = 'IDLE'
                        if error:
                            self.error = error
                    return
                self.phase = 'BUILDING'
            if self.phase == 'BUILDING':
                if self.adapter.busy() or not self.adapter.ready():
                    return
                if self.fresh_after is not None and id(snapshot) == self.fresh_after:
                    return
                displays = monitors.validate(snapshot)['monitors']
                if not displays:
                    self.adapter.refresh_monitors()
                    return
                devices = {row['device'] for row in displays}
                for token, device in tuple(self.owned.items()):
                    if device not in devices:
                        self.adapter.close(token)
                        self.owned.pop(token, None)
                rows = []
                for display in displays:
                    token = next((token for token, device in self.owned.items()
                                  if device == display['device'] and self.adapter.alive(token)), None)
                    if token is None:
                        token = self.adapter.create(display)
                        self.owned[token] = display['device']  # Track BEFORE tree/job setup may fail.
                    board = self.adapter.configure(token, display)
                    if board:
                        self.deferred_scans.add(board)
                    rows.append({'handle': token[1], 'device': display['device'], 'rect': display['work']})
                self.connected_topology = monitors.topology_key(snapshot)
                self.serial = self.host.reconcile(rows)
                self.phase, self.fresh_after = 'CONNECTING', None
            elif self.phase == 'CONNECTING':
                if self._status.get('completed_serial', 0) < self.serial:
                    if self._status.get('error'):
                        raise RuntimeError(self._status['error'])
                    return
                if not self._status.get('enabled'):
                    raise RuntimeError(self._status.get('error') or 'Desktop Host Unavailable')
                if set(self._status.get('handles', [])) != {token[1] for token in self.owned}:
                    raise RuntimeError('A desktop canvas was removed; reconnect the desktop canvases')
                self.phase = 'CONNECTED'
            elif self.phase == 'CONNECTED':
                if (self._status.get('need_rebind') or not self._status.get('enabled') or
                        set(self._status.get('handles', [])) != {token[1] for token in self.owned} or
                        self.connected_topology != monitors.topology_key(snapshot)):
                    self._begin_restore('BUILD', force_fresh=True)
                    return
            if self.phase in ('CONNECTED', 'CONNECTING', 'DETACHED') and not self.adapter.busy():
                for board in tuple(self.deferred_scans):
                    if self.adapter.scan(board):
                        self.deferred_scans.discard(board)
        except (OSError, RuntimeError, ValueError, ReferenceError, StopIteration) as exc:
            self._fail(exc)

    def cancel_pending(self):
        self.deferred_scans.clear()
        if self.phase == 'CLOSING':
            return  # load_pre shutdown must not be undone by the shared undo/load invalidator.
        if self.desired or self.owned or self.phase not in ('IDLE', 'DETACHED'):
            try:
                self.restore(close_windows=False)
            except (OSError, RuntimeError, ValueError) as exc:
                self.error, self.phase, self.desired = str(exc)[:2048], 'ERROR', False

    def shutdown(self):
        active = self.needs_service() or self._status.get('enabled', False)
        self.desired = False
        self.host.close()  # EOF/owner death covered by independent helpers; no UI blocking wait.
        self.owned.clear()
        self.deferred_scans.clear()
        self.phase, self.fresh_after = 'CLOSING' if active else 'IDLE', None


_service = Service()


def enable():
    _service.enable()


def restore():
    _service.restore()


def snapshot():
    return _service.snapshot()


def needs_service():
    return _service.needs_service()


def tick(snapshot):
    _service.tick(snapshot)


def cancel_pending():
    _service.cancel_pending()


def shutdown():
    _service.shutdown()


def load_pre(_dummy=None):
    shutdown()
