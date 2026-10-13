# SPDX-License-Identifier: GPL-2.0-or-later
"""Native clock/calculator nodes, with no evaluator threads or draw-time writes."""
from datetime import datetime
import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty
from bpy.types import Node, Operator
from blui_explorer.localization import iface
from . import model, safe_math, weather

CLOCK = 'BLUIDesktopClock'
CALCULATOR = 'BLUIDesktopCalculator'
WEATHER = 'BLUIDesktopWeather'


def _tree(context):
    space = context.space_data
    if space and space.type == 'NODE_EDITOR':
        tree = space.edit_tree or space.node_tree
        if tree and tree.bl_idname == model.TREE:
            return tree
    return None


def _expression_changed(node, _context):
    try:
        node.result = safe_math.format_result(safe_math.calculate(node.expression))
        node.error = ''
    except safe_math.CalculationError as error:
        node.result = ''
        node.error = str(error) if node.expression.strip() else ''


def _weather_location_changed(node, _context):
    node.weather_generation += 1
    for field in ('temperature', 'condition', 'humidity', 'wind_speed', 'observed_at',
                  'updated_at', 'weather_status', 'weather_error'):
        setattr(node, field, '')
    node.weather_stale = False


def redraw_clock_areas(context=None):
    """Called by the desktop runtime's one-second tick; retain no RNA pointers."""
    context = context or bpy.context
    manager = context.window_manager
    if not manager:
        return
    for window in manager.windows:
        for area in window.screen.areas:
            if area.type != 'NODE_EDITOR':
                continue
            space = area.spaces.active
            tree = space.edit_tree or space.node_tree
            if tree and tree.bl_idname == model.TREE:
                area.tag_redraw()


class BLUI_DesktopClock(Node):
    bl_idname = CLOCK
    bl_label = 'Clock'
    bl_icon = 'TIME'
    clock_format: StringProperty(name='Time Format', default='%H:%M:%S', maxlen=64)
    date_format: StringProperty(name='Date Format', default='%Y-%m-%d', maxlen=64)

    @classmethod
    def poll(cls, tree):
        return tree.bl_idname == model.TREE

    def init(self, _context):
        self.width = 220

    def draw_buttons(self, _context, layout):
        # The display is computed once, locally, without mutating the saved node.
        now = datetime.now()
        try:
            row = layout.row()
            row.alignment, row.scale_y = 'CENTER', 1.7
            row.label(text=now.strftime(self.clock_format), translate=False)
            if self.date_format:
                row = layout.row()
                row.alignment = 'CENTER'
                row.label(text=now.strftime(self.date_format), translate=False)
        except (ValueError, OverflowError):
            layout.label(text=iface('Invalid clock format'), icon='ERROR', translate=False)

    def draw_buttons_ext(self, _context, layout):
        layout.prop(self, 'clock_format', text=iface('Time Format'))
        layout.prop(self, 'date_format', text=iface('Date Format'))


class BLUI_DesktopCalculator(Node):
    bl_idname = CALCULATOR
    bl_label = 'Calculator'
    bl_icon = 'DRIVER'
    expression: StringProperty(name='Expression', default='', maxlen=safe_math.MAX_EXPRESSION,
                               update=_expression_changed)
    result: StringProperty(name='Result', default='')
    error: StringProperty(options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, tree):
        return tree.bl_idname == model.TREE

    def init(self, _context):
        self.width = 260

    def draw_buttons(self, _context, layout):
        result_row = layout.row()
        result_row.alignment, result_row.scale_y = 'RIGHT', 1.5
        if self.error:
            result_row.label(text=iface(self.error), icon='ERROR', translate=False)
        else:
            result_row.label(text=self.result or '0', translate=False)
        layout.prop(self, 'expression', text='')
        for keys in (('C', 'BACKSPACE', '(', ')'),
                     ('7', '8', '9', '/'), ('4', '5', '6', '*'),
                     ('1', '2', '3', '-'), ('0', '.', '=', '+')):
            row = layout.row(align=True)
            for key in keys:
                op = row.operator('wm.blui_desktop_calculator_key',
                                  text='' if key == 'BACKSPACE' else key,
                                  icon='BACK' if key == 'BACKSPACE' else 'NONE', translate=False)
                op.tree_name, op.node_name, op.key = self.id_data.name, self.name, key

    def draw_buttons_ext(self, _context, layout):
        layout.label(text=iface('Calculator Functions'), translate=False)
        layout.label(text='pi · e · sqrt · sin · cos · log · **', translate=False)


class BLUI_DesktopWeather(Node):
    bl_idname = WEATHER
    bl_label = 'Weather'
    bl_icon = 'WORLD'
    city: StringProperty(name='City', default='杭州', maxlen=128)
    latitude: FloatProperty(name='Latitude', default=30.2741, min=-90, max=90, precision=4,
                            update=_weather_location_changed)
    longitude: FloatProperty(name='Longitude', default=120.1551, min=-180, max=180, precision=4,
                             update=_weather_location_changed)
    weather_source: EnumProperty(name='Weather Source', items=(
        ('AUTO', 'Open-Meteo', 'Automatic global weather model'),
        ('CMA', 'CMA GRAPES', 'China Meteorological Administration model via Open-Meteo')),
        default='AUTO', update=_weather_location_changed)
    weather_enabled: BoolProperty(name='Online Weather', default=False)
    temperature: StringProperty(options={'SKIP_SAVE'})
    condition: StringProperty(options={'SKIP_SAVE'})
    humidity: StringProperty(options={'SKIP_SAVE'})
    wind_speed: StringProperty(options={'SKIP_SAVE'})
    observed_at: StringProperty(options={'SKIP_SAVE'})
    updated_at: StringProperty(options={'SKIP_SAVE'})
    weather_status: StringProperty(options={'SKIP_SAVE'})
    weather_error: StringProperty(options={'SKIP_SAVE'})
    weather_stale: BoolProperty(options={'SKIP_SAVE'})
    weather_generation: IntProperty(options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, tree):
        return tree.bl_idname == model.TREE

    def init(self, _context):
        self.width = 280

    def draw_buttons(self, _context, layout):
        layout.label(text=self.city, icon='WORLD', translate=False)
        row = layout.row()
        row.alignment, row.scale_y = 'CENTER', 1.7
        row.label(text=self.temperature or '— °C', translate=False)
        row = layout.row()
        row.alignment = 'CENTER'
        row.label(text=iface(self.condition) if self.condition else iface('Weather'), translate=False)
        if self.humidity or self.wind_speed:
            layout.label(text=(iface('Humidity') + ' ' + self.humidity + '  ·  ' +
                               iface('Wind') + ' ' + self.wind_speed), translate=False)
        if self.updated_at:
            layout.label(text=iface('Updated') + ': ' + self.updated_at, translate=False)
        if self.weather_stale:
            layout.label(text=iface('Offline weather cache'), icon='INFO', translate=False)
        elif self.weather_error:
            layout.label(text=iface(self.weather_error), icon='INFO', translate=False)
        elif self.weather_status:
            layout.label(text=iface(self.weather_status), translate=False)
        if not self.weather_enabled:
            layout.label(text=iface('Online refresh is off'), translate=False)
        op = layout.operator('wm.blui_desktop_weather_refresh', text=iface('Refresh Weather'),
                             icon='FILE_REFRESH', translate=False)
        op.tree_name, op.node_name = self.id_data.name, self.name
        # Attribution is present on the card even when used offline.
        layout.label(text=weather.ATTRIBUTION, translate=False)

    def draw_buttons_ext(self, _context, layout):
        op = layout.operator('wm.blui_desktop_weather_city', text=iface('Choose City'),
                             icon='WORLD', translate=False)
        op.tree_name, op.node_name = self.id_data.name, self.name
        layout.prop(self, 'city', text=iface('Display Label'))
        layout.prop(self, 'latitude', text=iface('Latitude'))
        layout.prop(self, 'longitude', text=iface('Longitude'))
        layout.prop(self, 'weather_source', text=iface('Weather Source'))
        layout.prop(self, 'weather_enabled', text=iface('Online Weather'))
        layout.label(text=iface('Coordinates are only sent when online refresh is enabled'),
                     icon='INFO', translate=False)


_KEYS = tuple((key, key, '') for key in ('C', 'BACKSPACE', '=', '(', ')', '/', '*', '-', '+', '.',
                                       '0', '1', '2', '3', '4', '5', '6', '7', '8', '9'))


class WM_OT_blui_desktop_calculator_key(Operator):
    bl_idname = 'wm.blui_desktop_calculator_key'
    bl_label = 'Calculator Key'
    bl_options = {'UNDO', 'INTERNAL'}
    tree_name: StringProperty(options={'SKIP_SAVE'})
    node_name: StringProperty(options={'SKIP_SAVE'})
    key: EnumProperty(items=_KEYS, options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return _tree(context) is not None

    def execute(self, context):
        tree = _tree(context)
        node = tree.nodes.get(self.node_name) if tree and tree.name == self.tree_name else None
        if not node or node.bl_idname != CALCULATOR:
            self.report({'WARNING'}, iface('Calculator changed; try again'))
            return {'CANCELLED'}
        if self.key == 'C':
            node.expression = ''
        elif self.key == 'BACKSPACE':
            node.expression = node.expression[:-1]
        elif self.key == '=':
            _expression_changed(node, context)
        elif len(node.expression) < safe_math.MAX_EXPRESSION:
            node.expression += self.key
        else:
            self.report({'WARNING'}, iface('Expression is too long'))
            return {'CANCELLED'}
        return {'FINISHED'}


class WM_OT_blui_desktop_weather_refresh(Operator):
    bl_idname = 'wm.blui_desktop_weather_refresh'
    bl_label = 'Refresh Weather'
    bl_options = {'INTERNAL'}
    tree_name: StringProperty(options={'SKIP_SAVE'})
    node_name: StringProperty(options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return _tree(context) is not None

    def execute(self, context):
        tree = _tree(context)
        node = tree.nodes.get(self.node_name) if tree and tree.name == self.tree_name else None
        if not node or node.bl_idname != WEATHER:
            self.report({'WARNING'}, iface('Weather card changed; try again'))
            return {'CANCELLED'}
        from . import runtime
        try:
            runtime.queue_weather(tree, node, force=True)
        except (RuntimeError, ValueError, OSError) as error:
            self.report({'WARNING'}, iface(str(error)))
            return {'CANCELLED'}
        node.weather_enabled = True
        return {'FINISHED'}


class WM_OT_blui_desktop_weather_city(Operator):
    bl_idname = 'wm.blui_desktop_weather_city'
    bl_label = 'Choose City'
    bl_options = {'UNDO', 'INTERNAL'}
    bl_property = 'city'
    tree_name: StringProperty(options={'SKIP_SAVE'})
    node_name: StringProperty(options={'SKIP_SAVE'})
    city: EnumProperty(items=tuple((key, label, '') for key, label, _lat, _lon in weather.CITIES),
                       options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return _tree(context) is not None

    def invoke(self, context, _event):
        context.window_manager.invoke_search_popup(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        tree = _tree(context)
        node = tree.nodes.get(self.node_name) if tree and tree.name == self.tree_name else None
        if not node or node.bl_idname != WEATHER:
            self.report({'WARNING'}, iface('Weather card changed; try again'))
            return {'CANCELLED'}
        _key, label, latitude, longitude = next(city for city in weather.CITIES if city[0] == self.city)
        node.city = iface(label)
        node.latitude, node.longitude = latitude, longitude
        return {'FINISHED'}


classes = (BLUI_DesktopClock, BLUI_DesktopCalculator, BLUI_DesktopWeather,
           WM_OT_blui_desktop_calculator_key, WM_OT_blui_desktop_weather_refresh,
           WM_OT_blui_desktop_weather_city)
