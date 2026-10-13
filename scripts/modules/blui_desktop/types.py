# SPDX-License-Identifier: GPL-2.0-or-later
"""Native node-tree cards, deliberately without executable node evaluation."""
import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty
from bpy.types import Node, NodeTree
from . import model
from blui_explorer.localization import iface


def canvas(context):
    space = context.space_data
    if space and space.type == 'NODE_EDITOR':
        tree = space.edit_tree or space.node_tree
        return tree if tree and tree.bl_idname == model.TREE else None
    return None


def path_icon(path, folder=False):
    if folder:
        return 'FILE_FOLDER'
    suffix = path.rsplit('.', 1)[-1].lower()
    if suffix in {'png', 'jpg', 'jpeg', 'bmp', 'webp', 'exr', 'tif', 'tiff'}:
        return 'FILE_IMAGE'
    if suffix in {'mp4', 'avi', 'mov', 'mkv', 'webm'}:
        return 'FILE_MOVIE'
    if suffix in {'txt', 'py', 'md', 'json', 'xml', 'csv'}:
        return 'FILE_TEXT'
    return 'FILE' if suffix != 'lnk' else 'LINKED'


def _folder_changed(tree, _context):
    tree.scan_generation += 1


def _background_changed(tree, _context):
    tree.background_generation += 1


class BLUI_DesktopTree(NodeTree):
    bl_idname = model.TREE
    bl_label = 'Desktop Canvas'
    bl_icon = 'NODETREE'
    directory: StringProperty(name='Folder', subtype='DIR_PATH', update=_folder_changed)
    service_status: StringProperty(options={'SKIP_SAVE'})
    scan_generation: IntProperty(options={'SKIP_SAVE'})
    layout_key: StringProperty()
    service_identity: StringProperty(options={'SKIP_SAVE'})
    board_id: StringProperty()
    monitor: StringProperty(name='Display')
    board_name: StringProperty(name='Desktop', default='Desktop')
    background_path: StringProperty(name='Image', subtype='FILE_PATH', update=_background_changed)
    background_enabled: BoolProperty(name='Show Background', update=_background_changed)
    background_fit: EnumProperty(name='Layout', default='FILL', items=tuple((key, label, '') for key, label in
        (('FIT', 'Fit'), ('FILL', 'Fill'), ('STRETCH', 'Stretch'), ('CENTER', 'Center'), ('TILE', 'Tile'), ('SPAN', 'Span Displays'))))
    background_opacity: FloatProperty(name='Opacity', default=1.0, min=0, max=1)
    background_align_x: FloatProperty(name='Horizontal Alignment', min=-1, max=1)
    background_align_y: FloatProperty(name='Vertical Alignment', min=-1, max=1)
    background_generation: IntProperty(options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, _context):
        return True


class BLUI_FileCard(Node):
    bl_idname = model.FILE
    bl_label = 'File Card'
    bl_icon = 'FILE'
    filepath: StringProperty(name='Path', subtype='FILE_PATH')
    folder: BoolProperty()

    @classmethod
    def poll(cls, tree):
        return tree.bl_idname == model.TREE

    def init(self, _context):
        self.width = 120
        self['blui_id'] = __import__('uuid').uuid4().hex

    def draw_buttons(self, _context, layout):
        from . import icon_cache, thumbnail_cache
        icon = thumbnail_cache.value(self.filepath, self.folder) or icon_cache.value(self.filepath)
        column = layout.column(align=True)
        column.alignment = 'CENTER'
        if not icon:
            # Built-in icon is immediate and remains a native file drag source on failure.
            icon = bpy.types.UILayout.bl_rna.functions['label'].parameters['icon'].enum_items[path_icon(self.filepath, self.folder)].value
        column.template_icon(icon_value=icon, scale=3.2, filepath=self.filepath)
        label = layout.row()
        label.alignment = 'CENTER'
        label.label(text=self.label[:20], translate=False)

    def draw_label(self):
        return self.label or self.filepath.rsplit('\\', 1)[-1]

    def copy(self, _node):
        self['blui_id'] = __import__('uuid').uuid4().hex


class BLUI_NoteCard(Node):
    bl_idname = model.NOTE
    bl_label = 'Note Card'
    bl_icon = 'TEXT'
    note: StringProperty(name='Note', default='')

    @classmethod
    def poll(cls, tree):
        return tree.bl_idname == model.TREE

    def init(self, _context):
        self.width = 240
        self.label = iface('Note Card')

    def draw_buttons(self, _context, layout):
        layout.prop(self, 'note', text='')


classes = (BLUI_DesktopTree, BLUI_FileCard, BLUI_NoteCard)
