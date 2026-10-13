BLUI 1.0.0 Windows x64 便携版 — 2026-10-13 桌面集成

完整解压后运行 BLUI-launcher.exe（或 BLUI.exe）。请保留 1.0、blui.shared
及 BLUI-fileicon.exe 等全部运行文件，不要只复制主程序。

本轮新增：
- 隐藏 Windows 原任务栏时，在隔离守护内临时释放其预留区；BLUI AppBar
  只保留自己的栏高，恢复或退出后还原原任务栏状态，不修改 SPI 工作区。
- 托盘读取真实注册图标与既有 Explorer 图标，显示透明图标和独立溢出列表；
  补充网络、音量、输入语言、通知、日历等系统入口，以及不抢焦点的独立悬停提示。
- 从任务栏设置或画布“显示器”菜单选择“使用 BLUI 替换 Windows 桌面”。
  默认关闭；所有显示器使用独立原生节点画布，沿用文件操作、异步缩略图、
  分组、小工具、背景与自动保存。可随时选择“恢复 Windows 桌面”。
- 桌面接管有双守护与持久恢复日记；正常恢复完成后才关闭专用桌面窗口，
  不改变普通 BLUI 窗口。父窗口意外消失时安全回收自身图形资源。
- 开始菜单仅在系统启用了完整休眠能力时显示“休眠”，执行前要求确认。
  不自动开启休眠，不修改电源配置；辅助进程超时不包含系统休眠时间。
- 修复任务栏高度/图标尺寸设置的真实保存请求入口遗漏。
- 修复辅助线程并行运行时，截图/多窗口重绘误判 Python 持锁状态的崩溃。

本机主要验收环境为 Windows 10 19045、两台显示器。Win11 分支保留，但尚未
在 Win11 实机验证，不能视为已完整兼容所有 Win11/XAML 托盘或混合 DPI 桌面。
历史托盘项只有可验证的原控件才代理点击；不猜回调，缺失公开接口时明确提示
使用原 Windows 通知区域。原系统区恢复入口始终保留。

桌面接入不是更换系统 Shell，不修改 Explorer/注册表，不强杀或重启 Explorer。
该版本仍不能完全取代资源管理器的全部系统功能；开始菜单没有直接 AppsFolder
全量索引、系统 Jump List 或 Windows 键接管。酷呆公开仓库目前只有说明文档，
桌面分区交互仅作参考，代码独立实现，并未声称移植其源码。

详见 DESKTOP_HOST.md、DESKTOP.md、NOTIFICATION_COMPATIBILITY.md、
NOTIFICATION_TRAY.md、TASKBAR_APPBAR.md、TASKBAR_PREVIEWS.md、START_MENU.md。

原发布包和用户窗口不会被此包覆盖或终止。
源码：https://github.com/LHT02/BlenderUI/tree/blui
