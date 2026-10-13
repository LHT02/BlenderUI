# BLUI 双栏原生开始菜单

开始菜单从独立任务栏的“开始”打开，使用原生 BLUI 控件与独立窗口；再次点击开始、
按 Escape 或点击其他应用可收起。文本编辑或确认弹窗活动时不会强制销毁窗口。

- 布局：参考 Open-Shell 的 Windows 7 双栏菜单，默认首页左栏放固定/最近程序；右栏保留
  用户文件、文档、图片、音乐、下载、计算机、控制面板和 Windows 设置。关机/电源在右下角，
  搜索在左栏底部。应用行使用左对齐、悬停高亮，不再用整排灰色按钮和 15 行分页。
- 搜索：只匹配已索引应用名称、分类，不运行输入文本、不搜索网络；搜索也覆盖尚未展开的文件夹。
- 所有程序：异步扫描 Windows 用户和公共 Programs 目录，保留 KnownFolder 重定向，
  只收录 `.lnk` 和 `.exe`。应用更新或路径变化时刷新列表，再尝试启动。
- 所有程序保留原有文件夹层级，合并用户/公共同名文件夹；点击箭头/文件夹可原位展开收起。
  左侧原生列表独立滚动，不滚动右侧系统入口或底部搜索、不改变菜单 DPI。返回可回到首页。
- 固定应用：使用应用行的右键菜单固定/取消固定；布局属于 BLUI，不修改 Windows 原生固定项。
- 最近打开：首页只记录从 BLUI 开始菜单成功提交启动的应用，不读取系统使用历史。
- 打开所在位置：只打开已索引应用对应的 Programs 文件夹，启动前重新验证文件身份；
  不解析任意输入路径、不启动该应用，也不增加最近使用记录。
- 文件、Windows 设置及电源入口只在明确点击时执行；锁屏、关机、重启需要二次确认。
  关机/重启不使用强制关闭参数，Windows 仍可提示保存或取消。
- 电源菜单仅在系统支持 S4 且启用了完整休眠文件时显示“休眠”；仅快速启动的缩减休眠文件不会误显示。
  能力查询在隔离进程异步进行，绘制只读缓存，不自动开启休眠或修改电源设置。
  点击后提示保存工作并二次确认，执行前重新核验；系统休眠期间不计入辅助进程的清醒时间超时。

图标异步使用 BLUI 的高质量快捷方式图标缓存；加载时显示原生占位图标。
固定和最近记录保存至桌面配置目录 `start-menu.json`，原子写入并维护有效 `.bak`。
多个 BLUI 实例若保存版本冲突，不覆盖较新记录；刷新菜单后再编辑。

限制：本轮不接管 Windows 按键、Explorer、系统 Shell，不安装或注入 Open-Shell。
无快捷方式的直接 AppsFolder/UWP 应用、系统 Jump List、Windows 搜索索引和应用商店
建议尚未接入；通过 Programs 快捷方式暴露的应用继续由 Windows 按正常关联启动。
扫描不跟随子目录 junction/reparse；最多 1024 应用、8192 条目、8 层目录、4 秒扫描。
64 个固定和 24 个最近项。某个重定向/网络目录卡住时只影响可终止的辅助进程，不占用
UI 主线程；已显示的列表仍可搜索，界面可继续操作。

设计参考（没有复制或链接源代码）：

- [Open-Shell-Menu](https://github.com/Open-Shell/Open-Shell-Menu)，MIT，
  [Programs/固定/最近菜单实现](https://github.com/Open-Shell/Open-Shell-Menu/blob/master/Src/StartMenu/StartMenuDLL/MenuContainer.cpp)
  中的 Win7 双栏、底部搜索、关机区域，以及
  [ProgramsTree](https://github.com/Open-Shell/Open-Shell-Menu/blob/master/Src/StartMenu/StartMenuDLL/ProgramsTree.cpp)
  的原位程序目录展开思路；仅参考结构与交互，不复制/链接实现。
- [Microsoft KnownFolderID](https://learn.microsoft.com/en-us/windows/win32/shell/knownfolderid)，
  [ShellExecute](https://learn.microsoft.com/en-us/windows/win32/api/shellapi/nf-shellapi-shellexecutew)，
  [Windows 设置 URI](https://learn.microsoft.com/en-us/windows/apps/develop/launch/launch-settings)，
  [ExitWindowsEx](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-exitwindowsex)。

回归：`test_start_menu.py` / `test_start_menu_tree.py` 仅操作自己的临时文件或纯内存，启动与电源全部 mock；
`check_start_menu_services.py` 只读取真实 Programs 并检查隔离 IPC/路径身份，不打开应用。
