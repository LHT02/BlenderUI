# BLUI 原生开始菜单

开始菜单从独立任务栏的“开始”打开，使用原生 BLUI 控件与独立窗口；再次点击开始、
按 Escape 或点击其他应用可收起。文本编辑或确认弹窗活动时不会强制销毁窗口。

- 搜索：只匹配已索引应用名称、分类，不运行输入文本、不搜索网络。
- 全部应用：异步扫描 Windows 用户和公共 Programs 目录，保留 KnownFolder 重定向，
  只收录 `.lnk` 和 `.exe`。应用更新或路径变化时刷新列表，再尝试启动。
- 固定应用：点应用右侧图钉。布局属于 BLUI，不修改 Windows 原生开始菜单固定项。
- 最近打开：只记录从 BLUI 开始菜单成功提交启动的应用，不读取系统使用历史。
- 文件、Windows 设置及电源入口只在明确点击时执行；锁屏、关机、重启需要二次确认。
  关机/重启不使用强制关闭参数，Windows 仍可提示保存或取消。

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
  与 [异步搜索管理](https://github.com/Open-Shell/Open-Shell-Menu/blob/master/Src/StartMenu/StartMenuDLL/SearchManager.cpp)。
- [Microsoft KnownFolderID](https://learn.microsoft.com/en-us/windows/win32/shell/knownfolderid)，
  [ShellExecute](https://learn.microsoft.com/en-us/windows/win32/api/shellapi/nf-shellapi-shellexecutew)，
  [Windows 设置 URI](https://learn.microsoft.com/en-us/windows/apps/develop/launch/launch-settings)，
  [ExitWindowsEx](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-exitwindowsex)。

回归：`test_start_menu.py` 仅操作自己的临时文件，启动与电源全部 mock；
`check_start_menu_services.py` 只读取真实 Programs 并检查隔离 IPC/路径身份，不打开应用。
