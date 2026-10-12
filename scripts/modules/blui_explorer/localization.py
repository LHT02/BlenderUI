# SPDX-License-Identifier: GPL-2.0-or-later
"""BLUI additions use Blender's language and interface/tooltip translation settings."""
import re

_TEXT = {
    'Close Workspace': ('关闭工作区', '關閉工作區'),
    'Replace Image': ('替换当前图像', '取代目前影像'),
    'Close Image': ('关闭图像', '關閉影像'),
    'Close the current temporary image after confirming unsaved changes': ('确认未保存改动后关闭当前临时图像', '確認未儲存變更後關閉目前暫存影像'),
    'Unsaved changes will be lost': ('存在未保存的改动，放弃后无法恢复', '有未儲存的變更，捨棄後無法復原'),
    'Close this document workspace?': ('确认关闭此文档工作区？', '確定關閉此文件工作區？'),
    'Save and Close': ('保存后关闭', '儲存後關閉'),
    'Close Without Saving': ('不保存并关闭', '不儲存並關閉'),
    'Discard and Continue': ('放弃改动并继续', '捨棄變更並繼續'),
    'Close': ('关闭', '關閉'),
    'Cancel': ('取消', '取消'),
    'Confirm Document Action': ('确认文档操作', '確認文件操作'),
    'Saving failed; the workspace remains open': ('保存失败，工作区保持打开', '儲存失敗，工作區保持開啟'),
    'Detach Editor to New Window': ('分离编辑器到新窗口', '將編輯器分離至新視窗'),
    'Move the editor into a new window, preserving its current document': ('将编辑器移动到新窗口并保留当前文档', '將編輯器移至新視窗並保留目前文件'),
    'Failed to detach editor into a new window': ('无法将编辑器分离到新窗口', '無法將編輯器分離至新視窗'),
    'Editor opened in a new window; source area could not be closed': ('已在新窗口打开编辑器，但原区域无法关闭', '已在新視窗開啟編輯器，但來源區域無法關閉'),
    'The last workspace cannot be removed': ('不能移除最后一个工作区', '無法移除最後一個工作區'),
    'More': ('更多', '更多'),
    'Open': ('打开', '開啟'),
    'Rename': ('重命名', '重新命名'),
    'Move to Recycle Bin': ('删除到回收站', '移至資源回收筒'),
    'Cut': ('剪切', '剪下'),
    'Copy': ('复制', '複製'),
    'Paste': ('粘贴', '貼上'),
    'Copy To...': ('复制到...', '複製到...'),
    'Move To...': ('移动到...', '移動到...'),
    'Copy Path': ('复制项目路径', '複製項目路徑'),
    'Copy Folder Path': ('复制文件夹路径', '複製資料夾路徑'),
    'Extract ZIP to Folder...': ('解压 ZIP 到文件夹...', '解壓縮 ZIP 至資料夾...'),
    'Extract ZIP to Folder': ('解压 ZIP 到文件夹', '解壓縮 ZIP 至資料夾'),
    'Create ZIP...': ('打包为 ZIP...', '壓縮為 ZIP...'),
    'Create 7Z...': ('打包为 7Z...', '壓縮為 7Z...'),
    'Open File Location': ('打开所在位置', '開啟檔案位置'),
    'Properties': ('属性', '內容'),
    'Windows Context Menu': ('Windows 上下文菜单', 'Windows 快顯功能表'),
    'Loading Windows menu...': ('正在加载 Windows 菜单...', '正在載入 Windows 功能表...'),
    'Windows menu helper unavailable': ('Windows 菜单助手不可用', 'Windows 功能表助手無法使用'),
    'Windows menu unavailable': ('Windows 菜单不可用', 'Windows 功能表無法使用'),
    'Retry Windows Menu': ('重新加载 Windows 菜单', '重新載入 Windows 功能表'),
    'Windows Command': ('Windows 菜单操作', 'Windows 功能表操作'),
    'Run Windows Menu Command': ('执行 Windows 菜单命令', '執行 Windows 功能表命令'),
    'This menu session expired. Open the context menu again.': ('菜单会话已失效，请重新打开菜单。', '功能表工作階段已失效，請重新開啟。'),
    'Selection changed. Open the context menu again.': ('选择已改变，请重新打开菜单。', '選取已變更，請重新開啟功能表。'),
    'Close existing Windows extension dialogs before opening another': ('请先关闭已有的 Windows 扩展窗口', '請先關閉現有的 Windows 擴充視窗'),
    'Close existing Windows extension dialogs before opening another menu': ('请先关闭已有的 Windows 扩展窗口再打开菜单', '請先關閉現有的 Windows 擴充視窗再開啟功能表'),
    'Windows menu helper exited. Retry to load a new session.': ('Windows 菜单助手已退出，可以重新加载。', 'Windows 功能表助手已結束，可重新載入。'),
    'Windows menu helper crashed or exited.': ('Windows 菜单助手崩溃或退出。', 'Windows 功能表助手當機或結束。'),
    'Windows menu timed out. BLUI is still available.': ('Windows 菜单加载超时，BLUI 仍可正常使用。', 'Windows 功能表載入逾時，BLUI 仍可正常使用。'),
    'System command timed out; its result is unknown. Check files before retrying.': ('系统命令超时，结果未知，请检查文件后再重试。', '系統命令逾時，結果未知，請檢查檔案後再重試。'),
    'View': ('视图', '檢視'),
    'Details': ('详细信息', '詳細資料'),
    'List': ('列表', '清單'),
    'Large Icons': ('大图标', '大型圖示'),
    'Hidden Items': ('隐藏项目', '隱藏項目'),
    'New': ('新建', '新增'),
    'Folder': ('文件夹', '資料夾'),
    'Text Document': ('文本文档', '文字文件'),
    'New Text File': ('新建文本文件', '新增文字檔案'),
    'Name': ('名称', '名稱'),
    'Choose Destination Folder': ('选择目标文件夹', '選擇目的資料夾'),
    'Create Archive': ('创建压缩文件', '建立壓縮檔'),
    'Archive name': ('压缩文件名', '壓縮檔名稱'),
    'Drop Files': ('拖放文件', '拖放檔案'),
    'Copy the full paths of the selected items, or the current folder': ('复制所选项目或当前文件夹的完整路径', '複製所選項目或目前資料夾的完整路徑'),
    'Rename this item without overwriting another file': ('重命名项目，不覆盖已有文件', '重新命名項目，不覆寫現有檔案'),
    'Copy or move selected items to a folder; existing files are never overwritten': ('复制或移动所选项目到文件夹，不覆盖已有文件', '複製或移動所選項目至資料夾，不覆寫現有檔案'),
    'Extract into a new sibling folder; use the 7-Zip system submenu for other formats': ('解压到同级新文件夹；其他格式请使用 7-Zip 系统子菜单', '解壓縮至同層新資料夾；其他格式請使用 7-Zip 系統子功能表'),
    'Show the selected item in Windows Explorer': ('在 Windows 资源管理器中显示所选项目', '在 Windows 檔案總管中顯示所選項目'),
    'An item with that name already exists': ('已有同名项目', '已有同名項目'),
    'No files or destination for this drop': ('没有拖放文件或目标文件夹', '沒有拖放檔案或目的資料夾'),
    'Move': ('移动', '移動'),
    'Create ZIP': ('打包 ZIP', '壓縮 ZIP'),
    'Create 7Z': ('打包 7Z', '壓縮 7Z'),
    'Extract ZIP': ('解压 ZIP', '解壓縮 ZIP'),
    '%s...': ('%s中...', '%s中...'),
    '%s... (%d queued)': ('%s中...（另有 %d 项排队）', '%s中...（另有 %d 項排隊）'),
    '%s completed': ('%s完成', '%s完成'),
    '%s failed': ('%s失败', '%s失敗'),
    'Enter a valid file name': ('请输入有效的文件名', '請輸入有效的檔案名稱'),
    'This name is not supported by Windows': ('Windows 不支持此文件名', 'Windows 不支援此檔案名稱'),
    'Destination folder does not exist': ('目标文件夹不存在', '目的資料夾不存在'),
    'Cannot place a folder inside itself: %s': ('不能将文件夹放入自身或其子目录：%s', '不能將資料夾放入自身或其子目錄：%s'),
    'Already exists (nothing overwritten): %s': ('已有同名项目（未覆盖）：%s', '已有同名項目（未覆寫）：%s'),
    'Archive already exists: %s': ('压缩文件已存在：%s', '壓縮檔已存在：%s'),
    'Destination already exists: %s': ('目标已存在：%s', '目的位置已存在：%s'),
    'Unsafe archive path: %s': ('压缩文件中存在不安全路径：%s', '壓縮檔包含不安全的路徑：%s'),
    'Archive links separately: %s': ('请单独压缩链接：%s', '請單獨壓縮連結：%s'),
    '7-Zip failed: %s': ('7-Zip 操作失败：%s', '7-Zip 操作失敗：%s'),
    'Select items from the same folder': ('请选择同一文件夹中的项目', '請選取同一資料夾中的項目'),
    'Install 7-Zip to create 7Z archives': ('创建 7Z 压缩文件需要安装 7-Zip', '建立 7Z 壓縮檔需要安裝 7-Zip'),
    'Archive contains a symbolic link': ('压缩文件含有符号链接', '壓縮檔含有符號連結'),
    '%d item(s) completed; failed on %s: %s': ('已完成 %d 项；%s 操作失败：%s', '已完成 %d 項；%s 操作失敗：%s'),
    'File task exited unexpectedly; check the source and destination before retrying': ('文件任务意外退出，请检查源文件和目标后再重试', '檔案工作意外結束，請檢查來源與目的位置後再重試'),
    'Ctrl: Copy': ('Ctrl：复制', 'Ctrl：複製'),
    'Shift: Move': ('Shift：移动', 'Shift：移動'),
    '%s %d item(s) to %s  (%s)': ('%s %d 个项目到 %s（%s）', '%s %d 個項目至 %s（%s）'),
}


def register():
    import bpy
    tables = {}
    for locale, column in (('zh_CN', 0), ('zh_HANS', 0), ('zh_TW', 1), ('zh_HANT', 1)):
        tables[locale] = {(context, text): values[column]
                          for text, values in _TEXT.items() for context in ('*', 'Operator', 'BLUI')}
    bpy.app.translations.register(__name__, tables)


def unregister():
    import bpy
    bpy.app.translations.unregister(__name__)


def iface(text):
    from bpy.app.translations import pgettext_iface
    return pgettext_iface(text, 'BLUI')


def message(text):
    """Translate service messages while preserving paths and native error details."""
    translated = iface(text)
    if translated != text:
        return translated
    for prefix in ('Cannot place a folder inside itself', 'Already exists (nothing overwritten)',
                   'Archive already exists', 'Destination already exists', 'Unsafe archive path',
                   'Archive links separately', '7-Zip failed'):
        if text.startswith(prefix + ': '):
            return iface(prefix + ': %s') % text[len(prefix) + 2:]
    match = re.match(r'^(\d+) item\(s\) completed; failed on (.*?): (.*)$', text)
    if match:
        return iface('%d item(s) completed; failed on %s: %s') % (int(match[1]), match[2], match[3])
    return text
