# BLUI 通知区接收器

独立 `notification_host.py` 进程接收真实 Windows Shell_NotifyIcon 消息，设计参考
[RetroBar](https://github.com/dremin/RetroBar) 与
[ManagedShell TrayService](https://github.com/cairoshell/ManagedShell/blob/master/src/ManagedShell.WindowsTray/TrayService.cs)。
本实现未复制第三方源码；Windows 协议结构遵循其跨位数接收协议及
[Microsoft NOTIFYICONDATA 文档](https://learn.microsoft.com/en-us/windows/win32/api/shellapi/ns-shellapi-notifyicondataw)。

## 行为与边界

- 显式启用时注册自己进程内的隐藏 Shell_TrayWnd / TrayNotifyWnd，广播一次
  TaskbarCreated，请应用重新登记通知图标。只抬自己的接收窗，不重排 Explorer。
- 每条通知消息同步转发给按完整系统路径、HWND/PID/线程/启动时间/窗口类复核的
  原 Explorer 通知栏。Windows 的通知图标、气泡、AppBar 与用户设置由 Explorer 保留。
- 不注入 DLL，不读写 Explorer 远程内存，不修改 EnableAutoTray、不安装任何 Shell 扩展，
  不杀进程或更换 Windows shell。未重新登记的既有图标仍在系统栏；不能承诺全量
  Win11 内建通知控件或不响应 TaskbarCreated 的历史应用已镜像。
- stdin EOF、正常关闭或原父进程死亡时，先销毁自身接收窗口，然后广播 TaskbarCreated
  恢复消息路由。父进程通过保留的只读内核句柄确认，PID 重用不能改变父身份。
- 图标复制到自己的 HICON 并在隔离进程用可信 user32/gdi32 转为透明 RGBA；图标数、
  消息和输出大小有上限。所有发送回调都要求已登记 key，并每条复核原 HWND 身份。
- 版本4用实际物理屏幕坐标及 uid 打包回调；包含单击、右键、双击、悬停通知。

## IPC

启动：打包 Python `-I -B -u notification_host.py OWNER_PID OWNER_START_TIME`。

stdin 单行 UTF-8 JSON，例如：

```json
{"command":"activate","key":"hwnd:123:4","event":"RIGHT","x":500,"y":1000}
```

event 为 LEFT / RIGHT / DOUBLE / HOVER_ENTER / HOVER_LEAVE；另接受 shutdown、snapshot、heartbeat。
stdout 为 enabled / error / revision / host_handle / icons；每个 icon 包含 key、根 owner 身份、
callback、version、tip、hidden 和32×32 top-down RGBA base64。客户端每行读取上限4MiB。
主 UI 仅消费内存快照，不能在绘制回调中启动进程、读文件或直接发送 Win32 消息。

## 安全回归

纯测试 test_notification_protocol.py 不调用 Win32，不创建/触发其他应用图标。
`--qa-private` 注册 BLUI_QA_NotificationHost / BLUI_QA_TrayNotifyWnd 专用私有窗口，
**不广播 TaskbarCreated、不截获系统通知、不转发 Explorer**。主代理可用真实自有通知窗口
单播 COPYDATA 和查看自有回调来验证接收与像素绘制；不能将该私有模式称为系统栏全量验证。
