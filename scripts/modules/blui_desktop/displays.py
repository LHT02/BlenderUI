# SPDX-License-Identifier: GPL-2.0-or-later
"""Native desktop windows explicitly bound to connected displays; no Windows virtual desktops."""
import os
import bpy
from bpy.props import StringProperty
from bpy.types import Operator, Menu
from . import model, runtime, session, monitors
from blui_explorer.localization import iface

_topology = ''


def open_display(context, device):
    from bl_operators.blui_desktop import _new_window, _initialize
    from . import window_placement
    snapshot = runtime.monitor_snapshot()
    display = next((row for row in snapshot['monitors'] if row['device'] == device), None)
    if display is None:
        raise ValueError(iface('Display is no longer connected'))
    tree = next((tree for tree in session.roots() if tree.monitor == device), None)
    existing = next((window for window in context.window_manager.windows for area in window.screen.areas
                     if area.type == 'NODE_EDITOR' and area.spaces.active.node_tree == tree and tree), None)
    if existing:
        window_placement.place(existing.blui_native_handle, display['work'], snapshot, preferred=device)
        return
    window = _new_window(context)
    area = max(window.screen.areas, key=lambda area: area.width * area.height)
    if tree is None:
        from .paths import desktop
        tree = _initialize(area, desktop())
        tree.monitor, tree.board_name = device, device
    else:
        area.type = 'NODE_EDITOR'
        space = area.spaces.active
        space.tree_type, space.node_tree, space.pin = model.TREE, tree, True
        space.show_region_ui = space.show_region_toolbar = False
    window_placement.place(window.blui_native_handle, display['work'], snapshot, preferred=device)


def topology_changed(snapshot):
    global _topology
    key = monitors.topology_key(snapshot)
    if key == _topology or runtime.interaction_busy(None):
        return
    _topology = key
    from . import window_placement
    rows = snapshot['monitors']
    primary = next((row['device'] for row in rows if row['primary']), '')
    for window in bpy.context.window_manager.windows:
        trees = [area.spaces.active.node_tree for area in window.screen.areas if area.type == 'NODE_EDITOR']
        tree = next((tree for tree in trees if tree and tree.board_id), None)
        if not tree:
            continue
        if not tree.monitor:
            tree.monitor = primary
        try:
            window_placement.recover(window.blui_native_handle, snapshot, preferred=tree.monitor)
        except (ValueError, OSError):
            pass


class WM_OT_blui_display_open(Operator):
    bl_idname = 'wm.blui_display_open'
    bl_label = 'Open Display Desktop'
    device: StringProperty(options={'SKIP_SAVE'})

    def execute(self, context):
        try:
            open_display(context, self.device)
        except (RuntimeError, ValueError, OSError, ReferenceError) as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}


class WM_OT_blui_displays_open(Operator):
    bl_idname = 'wm.blui_displays_open'
    bl_label = 'Open Desktops on All Displays'

    def execute(self, context):
        rows = runtime.monitor_snapshot()['monitors']
        if not rows:
            self.report({'INFO'}, iface('Loading...'))
            return {'CANCELLED'}
        for row in rows:
            try:
                open_display(context, row['device'])
            except (RuntimeError, ValueError, OSError, ReferenceError) as exc:
                self.report({'WARNING'}, str(exc))
                return {'CANCELLED'}
        return {'FINISHED'}


class WM_OT_blui_board_show(Operator):
    bl_idname = 'wm.blui_board_show'
    bl_label = 'Show Desktop Layout'
    board: StringProperty(options={'SKIP_SAVE'})

    def execute(self, context):
        tree = session.by_id(self.board)
        if not tree or context.area.type != 'NODE_EDITOR' or runtime.interaction_busy(None):
            return {'CANCELLED'}
        context.space_data.node_tree, context.space_data.pin = tree, True
        return {'FINISHED'}


class BLUI_MT_displays(Menu):
    bl_label = 'Displays'

    def draw(self, _context):
        self.layout.operator('wm.blui_displays_open', text=iface('Open Desktops on All Displays'), translate=False)
        for display in runtime.monitor_snapshot()['monitors']:
            op = self.layout.operator('wm.blui_display_open', text=display['device'], icon='WINDOW', translate=False)
            op.device = display['device']
        self.layout.separator()
        connected = {row['device'] for row in runtime.monitor_snapshot()['monitors']}
        for tree in session.roots():
            text = tree.board_name + (' · ' + iface('Display Disconnected') if tree.monitor and tree.monitor not in connected else '')
            op = self.layout.operator('wm.blui_board_show', text=text, icon='NODETREE', translate=False)
            op.board = tree.board_id


classes = (WM_OT_blui_display_open, WM_OT_blui_displays_open, WM_OT_blui_board_show, BLUI_MT_displays)
