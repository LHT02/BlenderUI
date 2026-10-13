# BLUI 通知区接收器

独立 `notification_host.py` 进程接收真实 Windows Shell_NotifyIcon 消息，设计参考
[RetroBar](https://github.com/dremin/RetroBar) 与
[ManagedShell TrayService](https://github.com/cairoshell/ManagedShell/blob/master/src/ManagedShell.WindowsTray/TrayService.cs)。
本实现未复制第三方源码；Windows 协议结构遵循其跨位数接收协议及
[Microsoft NOTIFYICONDATA 文档](https://learn.microsoft.com/en-us/windows/win32/api/shellapi/ns-shellapi-notifyicondataw)。
两参考项目均采用 Apache-2.0；本实现独立编写，不复制或链接其实现。详细版本能力、
系统入口 fallback 与原生验证证据见 [通知兼容性说明](NOTIFICATION_COMPATIBILITY.md)。

## 行为与边界

- 显式启用时注册自己进程内的隐藏 Shell_TrayWnd / TrayNotifyWnd，广播一次
  TaskbarCreated，请应用重新登记通知图标。只抬自己的接收窗，不重排 Explorer。
- 每条通知消息同步转发给按完整系统路径、HWND/PID/线程/启动时间/窗口类复核的
  原 Explorer 通知栏。Windows 的通知图标、气泡、AppBar 与用户设置由 Explorer 保留。
- 不注入 DLL，不读写 Explorer 远程内存，不修改 EnableAutoTray、不安装任何 Shell 扩展，
  不杀进程或更换 Windows shell。另在 helper 自有后台线程读取原 Explorer 已存在的
  UIAutomation/ITrayNotify 状态，历史图标 bootstrap **不依赖应用重新登记**；真实 HICON
  优先，必要时只从身份/前景/矩形验证过的原 Toolbar 按钮读取 glyph。无法验证的条目
  诚实降级，不用圆点或伪造 callback/version 宣称完整兼容。
- Win10 已公开的原 Toolbar 由其自身按真实通知版本处理单击/右键/双击；只有真实
  Invoke/default-action 的 UIA 项仅提供该动作。未公开的历史隐藏项可在用户显式点击时
  尝试公开 Invoke 原 Chevron，再 fresh 唯一定位实际 Toolbar 项；不改偏好/长期显隐，
  定位失败提示原通知区。该 on-demand 路径仍标 PARTIAL，尚无隐藏项 end-to-end 实测。
- 网络、音量、电源、输入语言、通知、日历、原通知区为独立系统入口，与 App 回调身份
  分离；只允许固定 key 与入口。真实系统 UIA 按钮不可用时使用固定 Windows 快捷键/
  设置页。INPUT fallback 是切换语言、POWER fallback 是电源设置，不冒称原生弹窗完全等价。
- stdin EOF、正常关闭或原父进程死亡时，先销毁自身接收窗口，然后广播 TaskbarCreated
  恢复消息路由。父进程通过保留的只读内核句柄确认，PID 重用不能改变父身份。
- 图标复制到自己的 HICON 并在隔离进程用可信 user32/gdi32 转为透明 RGBA；图标数、
  消息和输出大小有上限。真实回调必须已收到实际 NIM 登记，并逐条复核原 App HWND
  身份；历史 provider 则使用独立 RuntimeId/原控件能力与身份验证，不猜 App 消息。
- 版本4用实际物理屏幕坐标及 uid 打包回调；包含单击、右键、双击、悬停通知。
  原 Win10 Toolbar 忠实保留 Explorer 的事件翻译；LEAVE 可成功清理原控件 hot item，
  但 Explorer 不保证给 App 发 WM_MOUSELEAVE/NIN_POPUPCLOSE，不伪造该回调。

## IPC

启动：打包 Python `-I -B -u notification_host.py OWNER_PID OWNER_START_TIME`。

stdin 单行 UTF-8 JSON，例如：

```json
{"command":"activate","key":"hwnd:123:4","event":"RIGHT","x":500,"y":1000}
```

event 为 LEFT / RIGHT / DOUBLE / HOVER_ENTER / HOVER_LEAVE；另接受 shutdown、snapshot、heartbeat。
历史项动作按实际能力限制，不能把 event allowlist 当成每种 provider 均支持。
系统入口示例（不接受任意 URI、executable 或 HWND）：

```json
{"command":"system","key":"VOLUME","event":"LEFT"}
```

stdout 保持旧 enabled / error / revision / host_handle / icons 字段兼容，并可增加 platform、
controls、bootstrap。每个 icon 包含 key、实际 App 或 Explorer provider 身份、callback、version、
tip、hidden、32×32 top-down RGBA base64，可增加 backend/actions 与 Win10 Toolbar 几何字段。
CALLBACK / TOOLBAR / UIA / OVERFLOW / DISPLAY 明确区分直接回调、原控件代理、default action、
显式原 overflow 尝试和仅显示；UIA key 为绑定原 Explorer 创建身份与 RuntimeId 的 opaque token。
客户端每行读取上限4MiB；后台校验/像素准备，主线程每批最多8个 preview。
主 UI 仅消费内存快照，不能在绘制回调中启动进程、读文件或直接发送 Win32 消息。
集成保持 notification_client.start/poll/snapshot/close/command/icon_value，以及
notification_ui.logical_width/draw_icons/draw_notification；logical_width 自动计入系统入口。

## 安全回归

纯测试 test_notification_protocol.py 不调用 Win32，不创建/触发其他应用图标。
`--qa-private` 注册 BLUI_QA_NotificationHost / BLUI_QA_TrayNotifyWnd 专用私有窗口，
**不广播 TaskbarCreated、不截获系统通知、不转发 Explorer、不 bootstrap、不暴露系统动作**。主代理可用真实自有通知窗口
单播 COPYDATA 和查看自有回调来验证接收与像素绘制；不能将该私有模式称为系统栏全量验证。
主代理已在本机 Win10 19045 验证真实历史 glyph 与 OWN 原 Toolbar 回调/删除；具体动态
图标数不是兼容性承诺。Win11 分支仅有主流源码/SDK ABI/纯回归证据，未在 Win11 实机
进行全量验证，不宣称替代所有 Windows 内建通知行为。
