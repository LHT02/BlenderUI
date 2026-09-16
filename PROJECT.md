# BLUI 项目交接

## 当前状态（2026-09-17）

按用户要求完成本轮文件管理器改造、快捷方式图标修复，然后编译便携包、
提交并推送 GitHub，暂停进一步开发。仓库分支：`blui`；GitHub remote：`gh`。
接手时 HEAD：`ddca0fd5cc7`，已有 64 个未推送提交，本次随当前分支一并推送。

## 已完成

- 一级右键菜单：打开、重命名、回收站、剪切/复制/粘贴、复制到/移动到、
  复制路径、ZIP 解压、ZIP/7Z 压缩；空白菜单含新建、视图、排序和刷新。
- “更多”二级菜单：打开所在位置、属性和真实 Windows Shell 菜单，
  支持 7-Zip、TortoiseSVN 等动态嵌套子菜单。
- Shell 扩展枚举和执行均在独立 Python 辅助进程；同一 COM 会话保持命令编号有效。
  原子 JSON 消息文件异步通信，无主进程持久 Python 线程或阻塞管道读写。
  加载超时/崩溃显示错误并支持重试；执行超时不自动重试。
- 文件复制/移动/压缩使用独立进程 FIFO 任务队列；工具栏显示任务状态，
  失败弹窗。禁止覆盖同名文件及将文件夹复制到自身子树。
- 跨卷移动成功后才删除源文件；剪切完成后仅在剪贴板未改变时清理。
- 内部拖放保留 Blender 原生半透明预览、文件夹高亮和目标/复制移动提示。
  同卷默认移动，Ctrl 复制，Shift 移动；指针离开 BLUI 后移交 Windows OLE。
- 快捷方式保留真实 .lnk 文件名；复制/移动/删除操作快捷方式本身。
  文件夹快捷方式可进入目标；失效快捷方式保留可见。
- 图标在预览工作线程提取；Win32 top-down 图像转 ImBuf 时翻转一次，
  修复上下倒置。
- 右键保留多选，空白清选；Ctrl+A 包括目录但排除父目录；
  F5 刷新、Ctrl+Shift+N 新建文件夹。删除及剪贴板入口额外排除合成父目录。
- 修复新工具栏触发旧删除 poll 的空列表崩溃；刷新延迟到当前 RNA 上下文退出后。

## 代码布局

- `scripts/modules/blui_explorer/`：文件任务、隔离进程、消息通信、Win32 Shell 桥接。
- `scripts/startup/bl_operators/blui_file.py`：常用文件操作入口及任务队列。
- `scripts/startup/bl_ui/space_filebrowser_explorer.py`：菜单、工具栏、Shell 会话 UI。
- `source/blender/editors/space_file/file_blui_drop.c`：原生拖放命中、目标和提示。
- Windows 图标转换在 `filelist.cc`；拖动选择集及 OLE 移交在 windowmanager。

## 本轮验证

- Release 构建、安装通过；可执行文件 `D:/BlenderUI/build/bin/BLUI.exe`。
- 9 项独立服务测试通过：复制/移动/同名保护、自包含防护、ZIP/7Z、
  ZIP 路径穿越、Windows 文件名、Shell 崩溃/超时/巨大请求、真实扩展子菜单。
- `check_explorer.py`：全选、复制路径、重命名、新建、C 拖放入口、
  跨卷剪贴板复制/剪切、快捷方式与目标隔离通过。
- `check_explorer_interaction.py`：原生鼠标拖入文件夹、快捷方式进入目标、
  真实 7-Zip UI 会话通过；菜单和拖动截图保存在 `build/explorer-*.png`。
- 红上蓝下测试图标截图确认方向正确。
- 3 套键位配置回归通过。
- 旧拖放同名冲突、回收站删除文件及目录回归通过，父目录保留。
- `git diff --check` 通过。未宣称整套历史测试全部重跑。

## 包装与交付

- 使用已有 `D:/BlenderUI/_package.py` 的允许列表复制完整运行时，
  排除 PDB、构建工具、Python 缓存；不覆盖旧发行包。
- 新便携包：`D:/BlenderUI/dist/BLUI-1.0.0-windows-x64-20260917-explorer.zip`。
- 已完成打包、7-Zip 完整性校验及发行目录启动验证；旧发行包保持原样。
- 必须解压整个目录运行，不能只拷贝 BLUI.exe；隔离助手依赖内置 Python。
- 历史未跟踪 `blui/tools/check_navigation.py` 和 `.cmd` 原样保留，不纳入本次提交。

## 已知边界 / 后续再做

- 部分 Shell 扩展首次加载较慢；若菜单显示加载中，稍后重新展开。
- Windows 外部拖出 OLE 的真实跨应用交互未完成端到端自动化验证；
  内部原生拖放已验证。尚不声称完整替代 Windows Explorer。
- computer-use 捕获在本机报 `SetIsBorderRequired 0x80004002`，
  重试失败后改用 BLUI 自身截图和输入测试。
- 按用户最新要求到打包提交为止，之后暂停，不扩展新功能。
