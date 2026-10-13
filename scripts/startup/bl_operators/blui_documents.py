# SPDX-License-Identifier: GPL-2.0-or-later
"""Document-aware close/replace decisions. Saving never closes a cancelled file selector."""
import time
import json
import uuid
from dataclasses import dataclass, field

import bpy
from bpy.props import EnumProperty, StringProperty
from bpy.types import Operator
from blui_explorer.localization import iface

_requests = {}


def _documents(areas, window):
    result, seen = [], set()
    for area in areas:
        for space in area.spaces:
            data = (space.image if space.type == 'IMAGE_EDITOR' else
                    space.text if space.type == 'TEXT_EDITOR' else None)
            if data and data.as_pointer() not in seen:
                seen.add(data.as_pointer())
                owner = next((w for w in bpy.context.window_manager.windows if area in list(w.screen.areas)), window)
                result.append((owner, area, space, data))
    return result


def _dirty(data):
    return data.is_dirty


@dataclass
class Request:
    window: object
    area: object
    action: str
    workspace: str
    filepath: str
    documents: list
    dock_arguments: str = ''
    saving: object = None
    saw_selector: bool = False
    started: float = 0.0
    previous_views: list = field(default_factory=list)
    previous_editors: list = field(default_factory=list)

    def restore_views(self):
        for area, kind in reversed(self.previous_editors):
            try:
                area.type = kind
            except ReferenceError:
                pass
        self.previous_editors.clear()
        for window, workspace, screen in reversed(self.previous_views):
            try:
                if window in list(bpy.context.window_manager.windows) and workspace.name in bpy.data.workspaces:
                    window.workspace = workspace
                    if screen.name in bpy.data.screens:
                        window.screen = screen
            except ReferenceError:
                pass
        self.previous_views.clear()

    def show_for_save(self, window, area, space):
        if area not in list(window.screen.areas):
            owner = next(((workspace, screen) for workspace in bpy.data.workspaces
                          for screen in workspace.screens if area in list(screen.areas)), None)
            if not owner:
                raise RuntimeError(iface('Saving failed; the workspace remains open'))
            if not any(w == window for w, _ws, _screen in self.previous_views):
                self.previous_views.append((window, window.workspace, window.screen))
            window.workspace, window.screen = owner
        if area.spaces.active != space:
            if not any(saved_area == area for saved_area, _kind in self.previous_editors):
                self.previous_editors.append((area, area.type))
            area.type = space.type
            if area.spaces.active != space:
                raise RuntimeError(iface('Saving failed; the workspace remains open'))

    def valid(self):
        try:
            if self.window not in list(bpy.context.window_manager.windows):
                return False
            if self.action == 'WORKSPACE' and self.workspace not in bpy.data.workspaces:
                return False
            for _window, area, space, data in self.documents:
                if space not in list(area.spaces):
                    return False
                current = space.image if space.type == 'IMAGE_EDITOR' else space.text
                if current != data:
                    return False
            return True
        except ReferenceError:
            return False

    def finish(self):
        if not self.valid():
            self.restore_views()
            return
        self.restore_views()
        with bpy.context.temp_override(window=self.window, area=self.area):
            if self.action == 'WINDOW':
                bpy.ops.wm.window_close(force_close=True)
            elif self.action == 'WORKSPACE':
                bpy.ops.workspace.delete(confirmed=True, workspace=self.workspace)
            elif self.action == 'AREA':
                bpy.ops.screen.area_close(confirmed=True)
            elif self.action == 'OPEN_IMAGE':
                bpy.ops.image.open(filepath=self.filepath, confirmed=True)
            elif self.action == 'NEW_IMAGE':
                bpy.ops.image.new('INVOKE_DEFAULT', confirmed=True)
            elif self.action == 'PASTE_IMAGE':
                bpy.ops.image.clipboard_paste(confirmed=True)
            elif self.action == 'IMAGE':
                bpy.ops.image.document_clear(confirmed=True)
            elif self.action == 'DOCK':
                bpy.ops.screen.area_dock(confirmed=True, **json.loads(self.dock_arguments))

    def save_next(self):
        for window, area, space, data in self.documents:
            if not _dirty(data):
                continue
            self.show_for_save(window, area, space)
            region = next((r for r in area.regions if r.type == 'WINDOW'), None)
            with bpy.context.temp_override(window=window, area=area, region=region, space_data=space):
                path = data.filepath_raw if space.type == 'IMAGE_EDITOR' else data.filepath
                if path and not path.startswith('<'):
                    result = bpy.ops.image.save() if space.type == 'IMAGE_EDITOR' else bpy.ops.text.save()
                    if result != {'FINISHED'} or _dirty(data):
                        raise RuntimeError(iface('Saving failed; the workspace remains open'))
                else:
                    result = (bpy.ops.image.save_as('INVOKE_DEFAULT') if space.type == 'IMAGE_EDITOR'
                              else bpy.ops.text.save_as('INVOKE_DEFAULT'))
                    if result != {'RUNNING_MODAL'}:
                        raise RuntimeError(iface('Saving failed; the workspace remains open'))
                    self.saving = data
                    self.saw_selector = False
                    self.started = time.monotonic()
                    return False
        self.finish()
        return True


def _await_save():
    for token, request in list(_requests.items()):
        if not request.saving:
            continue
        if not request.valid():
            request.restore_views()
            _requests.pop(token, None)
            continue
        selector_open = any(area.type == 'FILE_BROWSER' and area.spaces.active.active_operator
                            for window in bpy.context.window_manager.windows for area in window.screen.areas)
        request.saw_selector |= bool(selector_open)
        if selector_open:
            continue
        if not request.saw_selector and time.monotonic() - request.started < 1.0:
            continue
        if _dirty(request.saving):
            # Cancelled Save As: keep the document and workspace intact.
            request.restore_views()
            _requests.pop(token, None)
            continue
        request.saving = None
        try:
            if request.save_next():
                _requests.pop(token, None)
        except (RuntimeError, OSError) as exc:
            request.restore_views()
            print('BLUI document save:', exc)
            _requests.pop(token, None)
    return 0.1 if any(r.saving for r in _requests.values()) else None


class WM_OT_blui_document_guard(Operator):
    bl_idname = 'wm.blui_document_guard'
    bl_label = 'Close Workspace'
    action: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    workspace: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    filepath: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    dock_arguments: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    def invoke(self, context, _event):
        window, area = context.window, context.area
        if self.action in {'WINDOW', 'WORKSPACE'}:
            area = next(iter(window.screen.areas), None)
        if self.action == 'WORKSPACE':
            workspace = bpy.data.workspaces.get(self.workspace)
            if not workspace:
                return {'CANCELLED'}
            areas = [a for screen in workspace.screens for a in screen.areas]
            documents = _documents(areas, window)
        elif self.action == 'WINDOW':
            documents = []
            for candidate in context.window_manager.windows:
                ancestor = candidate
                while ancestor and ancestor != window:
                    ancestor = ancestor.parent
                if ancestor:
                    documents.extend(_documents(candidate.screen.areas, candidate))
        else:
            documents = _documents([area], window)
        request = Request(window, area, self.action, self.workspace, self.filepath, documents, self.dock_arguments)
        if not documents:
            request.finish()
            return {'FINISHED'}
        for token, pending in list(_requests.items()):
            if not pending.valid():
                _requests.pop(token, None)
            elif pending.window == window and pending.action == self.action:
                if pending.saving:
                    return {'CANCELLED'}
                _requests.pop(token, None)
        token = uuid.uuid4().hex
        _requests[token] = request
        dirty = any(_dirty(data) for _w, _a, _s, data in documents)
        action = self.action
        def draw(self, _context):
            layout = self.layout
            question = 'Unsaved changes will be lost' if dirty else 'Replace this editor?' if action == 'DOCK' else 'Close this document workspace?'
            layout.label(text=iface(question),
                         icon='ERROR' if dirty else 'QUESTION', translate=False)
            for _window, _area, _space, data in documents:
                layout.label(text=data.name, translate=False)
            if dirty:
                op = layout.operator('wm.blui_document_decision', text=iface('Save and Continue' if action == 'DOCK' else 'Save and Close'),
                                     icon='FILE_TICK', translate=False)
                op.token, op.choice = token, 'SAVE'
            label = ('Discard and Continue' if action in {'OPEN_IMAGE', 'NEW_IMAGE', 'PASTE_IMAGE', 'DOCK'} else
                     'Close Without Saving' if dirty else 'Close')
            op = layout.operator('wm.blui_document_decision', text=iface(label), icon='X', translate=False)
            op.token, op.choice = token, 'DISCARD'
            op = layout.operator('wm.blui_document_decision', text=iface('Cancel'), translate=False)
            op.token, op.choice = token, 'CANCEL'
        title = 'Replace Editor' if self.action == 'DOCK' else 'Replace Image' if self.action == 'OPEN_IMAGE' else 'Close Workspace'
        context.window_manager.popup_menu(draw, title=iface(title), icon='QUESTION')
        return {'FINISHED'}


class WM_OT_blui_document_decision(Operator):
    bl_idname = 'wm.blui_document_decision'
    bl_label = 'Confirm Document Action'
    token: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    choice: EnumProperty(items=(('SAVE', 'Save', ''), ('DISCARD', 'Discard', ''), ('CANCEL', 'Cancel', '')),
                         options={'HIDDEN', 'SKIP_SAVE'})

    def execute(self, _context):
        request = _requests.get(self.token)
        if not request or not request.valid():
            _requests.pop(self.token, None)
            return {'CANCELLED'}
        try:
            if self.choice == 'SAVE':
                if not request.save_next():
                    if not bpy.app.timers.is_registered(_await_save):
                        bpy.app.timers.register(_await_save, first_interval=0.2)
                    return {'FINISHED'}
            elif self.choice == 'DISCARD':
                request.finish()
        except (RuntimeError, OSError) as exc:
            request.restore_views()
            self.report({'ERROR'}, str(exc))
            _requests.pop(self.token, None)
            return {'CANCELLED'}
        _requests.pop(self.token, None)
        return {'FINISHED'}


class WM_OT_blui_close_moved_window(Operator):
    bl_idname = 'wm.blui_close_moved_window'
    bl_label = 'Finish Moving Editor'
    bl_options = {'INTERNAL'}
    source: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    replacement: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    source_space: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    def execute(self, context):
        source, replacement = int(self.source), int(self.replacement)
        source_space = int(self.source_space or '0')
        manager = context.window_manager
        def close_after_modal_finished():
            try:
                windows = {w.as_pointer(): w for w in manager.windows}
                if source in windows and replacement in windows:
                    screen = windows[source].screen
                    # A queued workspace/editor change must not close a new document.
                    if len(screen.areas) != 1 or (source_space and
                            screen.areas[0].spaces.active.as_pointer() != source_space):
                        return None
                    with bpy.context.temp_override(window=windows[source]):
                        bpy.ops.wm.window_close(force_close=True)
            except (ReferenceError, RuntimeError):
                # Loading another session or closing either window invalidates this request.
                return None
            return None
        # The corner handler must finish before its window/event storage is freed.
        bpy.app.timers.register(close_after_modal_finished, first_interval=0.01)
        return {'FINISHED'}


classes = (WM_OT_blui_document_guard, WM_OT_blui_document_decision, WM_OT_blui_close_moved_window)
