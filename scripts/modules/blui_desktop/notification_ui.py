# SPDX-License-Identifier: GPL-2.0-or-later
"""Native notification icons and an independent, scrolling overflow window."""
import bpy
from bpy.props import CollectionProperty, IntProperty, PointerProperty, StringProperty
from bpy.types import Operator, PropertyGroup, UIList
from blui_explorer.localization import iface
from . import notification_client as client, taskbar_windows

ICON_SLOT = 24
_fingerprint = None


def _system_rows(value):
    return [dict(item, key='system:' + item['key'], tip=iface(item['label']),
                 hidden=False, cache_key='', control=True) for item in value.get('controls', [])]


def _actionable(icon):
    return bool(icon.get('actions', icon.get('callback', False)))


def _partition(maxicons):
    if type(maxicons) is not int or not 0 <= maxicons <= 16:
        raise ValueError('Invalid notification inline icon count')
    value = client.snapshot()
    if not value['enabled']:
        return [], []
    visible = [row for row in value['icons'] if not row['hidden']]
    inline = visible[:maxicons]
    keys = {row['key'] for row in inline}
    return inline + _system_rows(value), [row for row in value['icons'] if row['key'] not in keys]


def logical_width(maxicons=6):
    inline, overflow = _partition(maxicons)
    return (len(inline) + bool(overflow)) * ICON_SLOT


def draw_icons(layout, _context, maxicons=6, button_height=40):
    inline, overflow = _partition(maxicons)
    row = layout.row(align=True)
    row.operator_context = 'INVOKE_DEFAULT'
    for icon in inline:
        button = row.row(align=True)
        button.ui_units_x = ICON_SLOT / 20
        button.scale_y = button_height / 20
        button.enabled = _actionable(icon)
        value = client.icon_value(icon)
        kwargs = {'icon_value': value} if value else {'icon': icon.get('icon', 'DOT')}
        button.operator('wm.blui_notification_action', text='', **kwargs).key = icon['key']
    if overflow:
        button = row.row(align=True)
        button.ui_units_x = ICON_SLOT / 20
        button.scale_y = button_height / 20
        button.operator('wm.blui_notification_overflow', text='', icon='TRIA_UP')


def _position(context, event=None):
    # Click-time, verified own-HWND coordinates. No OS work occurs in draw.
    rect = taskbar_windows.window_placement.bounds(context.window.blui_native_handle)['rect']
    x = rect[0] + (event.mouse_x if event else context.window.width // 2)
    y = rect[1] + (context.window.height - event.mouse_y if event else context.window.height)
    return max(-32768, min(32767, int(x))), max(-32768, min(32767, int(y)))


class WM_OT_blui_notification_action(Operator):
    bl_idname = 'wm.blui_notification_action'
    bl_label = 'Notification Icon'
    key: StringProperty(options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return bool(context.window and context.window.blui_shell_role in {'TASKBAR', 'TASK_CHOOSER'})

    @classmethod
    def description(cls, _context, properties):
        value = client.snapshot()
        icon = next((row for row in value['icons'] + _system_rows(value) if row['key'] == properties.key), None)
        if icon and icon.get('backend') == 'UIA':
            return icon['tip'] + '\n' + iface('Historical icon: default action only')
        if icon and icon.get('backend') in {'DISPLAY', 'OVERFLOW'}:
            return icon['tip'] + '\n' + iface('Historical icon: use Original Windows Notification Area')
        return icon['tip'] if icon and icon['tip'] else iface('Notification Icon')

    def _action(self, context, event=None):
        action = ('RIGHT' if event and event.type == 'RIGHTMOUSE' else
                  'DOUBLE' if event and event.value == 'DOUBLE_CLICK' else 'LEFT')
        try:
            if self.key == 'system:ORIGINAL_TRAY' and action == 'LEFT':
                # Restoring is asynchronous in the existing crash-safe owner
                # service. Do not immediately send Win+B to an invisible tray.
                return bpy.ops.wm.blui_windows_taskbar(action='restore')
            client.command(self.key, action, *_position(context, event))
        except (OSError, RuntimeError, ValueError) as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        if (context.window.blui_shell_role == 'TASK_CHOOSER' and
                taskbar_windows.menu_state(context.window).get('kind') == 'NOTIFICATION'):
            taskbar_windows.close_window(context.window)
        return {'FINISHED'}

    def invoke(self, context, event):
        return self._action(context, event)

    def execute(self, context):
        return self._action(context)


class BLUI_NotificationItem(PropertyGroup):
    key: StringProperty(options={'SKIP_SAVE'})
    label: StringProperty(options={'SKIP_SAVE'})
    cache_key: StringProperty(options={'SKIP_SAVE'})
    icon: StringProperty(default='DOT', options={'SKIP_SAVE'})
    actionable: IntProperty(default=0, min=0, max=1, options={'SKIP_SAVE'})


class BLUI_NotificationSettings(PropertyGroup):
    items: CollectionProperty(type=BLUI_NotificationItem, options={'SKIP_SAVE'})
    active: IntProperty(default=-1, min=-1, options={'SKIP_SAVE'})


class BLUI_UL_notification_icons(UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname):
        layout.operator_context = 'INVOKE_DEFAULT'
        value = client.icon_value({'cache_key': item.cache_key})
        kwargs = {'icon_value': value} if value else {'icon': item.icon}
        layout.enabled = bool(item.actionable)
        op = layout.operator('wm.blui_notification_action', text=item.label or iface('Notification Icon'),
                             emboss=False, translate=False, **kwargs)
        op.key = item.key

    def draw_filter(self, _context, _layout):
        pass


def sync(context=None):
    """Update transient list RNA only at runtime/event boundaries, never in draw."""
    global _fingerprint
    context = context or bpy.context
    wm = getattr(context, 'window_manager', None)
    settings = getattr(wm, 'blui_notification_settings', None) if wm else None
    if settings is None:
        return False
    value = client.snapshot()
    rows = value['icons'] + _system_rows(value)
    fingerprint = (settings.as_pointer(), tuple((row['key'], row['tip'], row['cache_key'],
                    row.get('icon', 'DOT'), _actionable(row)) for row in rows))
    if fingerprint == _fingerprint and len(settings.items) == len(rows):
        return False
    settings.items.clear()
    for row in rows:
        item = settings.items.add()
        item.key, item.label, item.cache_key = row['key'], row['tip'].replace('\n', ' '), row['cache_key']
        item.icon, item.actionable = row.get('icon', 'DOT'), int(_actionable(row))
    settings.active = -1
    _fingerprint = fingerprint
    return True


class WM_OT_blui_notification_overflow(Operator):
    bl_idname = 'wm.blui_notification_overflow'
    bl_label = 'Show Notification Icons'

    def execute(self, context):
        if not client.snapshot()['enabled']:
            return {'CANCELLED'}
        source = context.window
        window = next(iter(taskbar_windows.role_windows('TASK_CHOOSER')), None)
        if window is None:
            window = taskbar_windows.create(context, 'TASK_CHOOSER', 420, 560)
        taskbar_windows.set_menu_state(window, {'kind': 'NOTIFICATION', 'device': taskbar_windows.device(source)})
        sync(context)
        taskbar_windows.place_menu(window, source, 420, 560)
        return {'FINISHED'}


def draw_notification(layout, context):
    value = client.snapshot()
    header = layout.row()
    header.label(text=iface('Notification Area'), translate=False)
    header.operator('wm.window_close', text='', icon='X').force_close = True
    if value['error']:
        layout.label(text=iface('Notification area is unavailable'), icon='ERROR', translate=False)
    bootstrap = value.get('bootstrap', {})
    if bootstrap.get('state') in {'PARTIAL', 'UNAVAILABLE'}:
        layout.label(text=iface('Some historical icons require the original Windows tray'), icon='INFO', translate=False)
        layout.operator('wm.blui_windows_taskbar', text=iface('Original Windows Notification Area'),
                        icon='WINDOW', translate=False).action = 'restore'
    if not value['icons'] and not value.get('controls'):
        layout.label(text=iface('No Notification Icons'), translate=False)
        return
    settings = context.window_manager.blui_notification_settings
    logical = context.region.height / context.preferences.system.ui_scale
    rows = max(1, min(23, int(max(0, logical - 100) // 20)))
    layout.template_list('BLUI_UL_notification_icons', 'notification_icons', settings, 'items',
                         settings, 'active', rows=rows, maxrows=rows)


def register_props():
    global _fingerprint
    _fingerprint = None
    bpy.types.WindowManager.blui_notification_settings = PointerProperty(type=BLUI_NotificationSettings,
                                                                       options={'SKIP_SAVE'})


def unregister_props():
    global _fingerprint
    _fingerprint = None
    if hasattr(bpy.types.WindowManager, 'blui_notification_settings'):
        del bpy.types.WindowManager.blui_notification_settings


classes = (BLUI_NotificationItem, BLUI_NotificationSettings, BLUI_UL_notification_icons,
           WM_OT_blui_notification_action, WM_OT_blui_notification_overflow)
