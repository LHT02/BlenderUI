# BLUI 项目交接

## 2026-10-13 桌面与系统栏集成发布（Win10 优先）

- Release 最终编译成功；551 项纯回归全部通过（desktop-shell-pure-final.log）。本机 Windows 10 19045、双 2560×1440/96 DPI 为实机验收环境；Win11 分支保留，但没有 Win11/XAML 或混合 DPI 实机验收，历史自动隐藏托盘的 on-demand OVERFLOW 路由仍按兼容说明标记 PARTIAL，不宣传全系统完全替代。
- 原任务栏预留回收真机 PASS：1400→1440，自有 AppBar 56px 单独预留到1384，正常恢复及仅终止 OWN helper 后第二守护均还原原位/两屏工作区/原任务栏可见性（taskbar-reclaim-native.log）。托盘真实 OWN 图标原 Explorer 回调、透明像素与独立 NOACTIVATE 提示真机 PASS；不存在公开可验证入口的历史图标回退原系统区，未操作第三方真实图标。
- 最终包内桌面 service 双屏启用/恢复两轮、异步 OWN PNG 缩略图、board/layout 复用、普通窗口保持不变 PASS（package-desktop-service-gil-fixed.log）；原生父死亡回收及 save/open 不泄漏临时桌面 UI，在 PYTHONMALLOC=debug 下 PASS（package-desktop-lifecycle-gil-fixed.log）。DESKTOP-only DPI scope 保持原 UI thread/NORMAL18，仅新 DESKTOP 匹配真实 host34。
- 本轮真实截图崩溃由 debug allocator 确认无 GIL 的 Python 内存访问，已修正旧持锁判断。相同真实 worker/绘制回调下，debugmalloc 连续8张与普通启动路径连续8张截图、原生 capture/框选守门、实际 Calculator 高亮、restore ack 后仅关自有桌面均 PASS（package-desktop-gil-stress-8.log、package-desktop-gil-normal-8.log）。此前无栈挂起未证明同一根因，不宣称绝对防崩。
- 系统完整休眠能力只读检测、真实 helper 请求、任务栏设置 OWN 临时目录保存/读回 PASS（power-settings-real-ipc-final.log）；真实 bpy 菜单能力开/关及确认入口 PASS。零休眠/睡眠/关机操作，未修改系统电源配置。
- 新便携包：D:/BlenderUI/dist/BLUI-1.0.0-windows-x64-20261013-desktop-shell-integration.zip；125816692 bytes，3855 entries 全量 CRC PASS，无 pyc/PDB/cache。源码与包内96 desktop/explorer模块及8文档 SHA 一致，改动103文件均 UTF-8 无 BOM，git diff --check PASS；旧发布包保留。只重建本轮尚未交付的草稿 ZIP，没有删除用户内容。
- 最终 BLUI.exe SHA256：7291EB4A80BB87CB10E28C1F0020EFAD8FBE6B30CBEF392D2ED61E17B7E2F7F4；ZIP SHA256：2B1322BAB0A5574C7652C172C9FA786BBC42B68F54AD92FD172747CB66DEABE2。源码发布分支为 gh/blui（LHT02/BlenderUI），不推 origin 上游；check_navigation.py/.cmd 为用户未跟踪文件，不纳入本轮提交。
- 使用：完整解压运行 BLUI-launcher.exe；任务栏设置或画布“显示器”菜单显式启用“使用 BLUI 替换 Windows 桌面”，随时可恢复。桌面接入默认关闭，有双守护及持久恢复日记，不改系统 Shell/注册表，不杀/重启 Explorer；完整边界见随包 README-BLUI.txt、DESKTOP_HOST.md、NOTIFICATION_COMPATIBILITY.md。

## 2026-10-13 第二轮开发与验收记录（已收尾）

- GIL修复编译PASS；相同包内hover夹具在PYTHONMALLOC=debug、真实worker并发下完整PASS（原生capture/框选守门、截图、实际高亮、restore ack、布局/普通窗口保留）。README补该稳定性修复；继续连续截图压力与native父死亡/save-load复核，不宣称绝对防崩。接口契约：https://docs.python.org/3.10/c-api/init.html#c.PyGILState_Check。

- 加强诊断在OWN QA启用PYTHONMALLOC=debug后明确报“Python memory allocator called without holding the GIL”。查实旧PyC_IsInterpreterActive用PyThreadState_GetDict检查进程current threadstate，SCREENscreenshot pyop先释放GIL、其它worker运行时会误认为主线程持锁，CTX重绘的PyDict/Unicode操作跳过Ensure。现只改该工具判断为Py_IsInitialized && PyGILState_Check（CPython3.10官方当前线程持锁接口），不吞draw异常、不禁线程/截图、不改实际context；待编译/debugmalloc压力与普通路径实测。

- 最终增量编译与543纯回归PASS，包内service双屏2cycles/真实缩略图/条件休眠PASS；但hover夹具phase3在screen.screenshot强制多窗重绘时真实EXCEPTION_ACCESS_VIOLATION，栈为Python enum转换/background._draw读取space.type，尚未进入RESTORE/关闭。暂停发布，保存完整native/Python栈并并行只读审计回调context/GIL及fixture ctypes ABI；不能归因已修复或把失败计为通过。独立guardian退出后无残留host helper，继续核验journal恢复。

- 收尾编译发现新增进度COM守门的成员名笔误，已改用现有m_bluiDesktopWindow并同步回归；不改变DESKTOP隔离范围，重新编译和包内实机验收后再发布。

- 最终诊断版hover恢复在原thread18/Normal18、Desk34/Host34下连续3次完整PASS，真实capture与框选仍阻塞、普通未按下按钮实际高亮已视检、ack后仅关闭own Desk并保持layout；保留已空的OWN诊断目录防guardian写入竞态。另一次无栈合成输入QA出现挂起，物理恢复日记已空后只结束精确OWN QA；未重现、未声称根因已确诊。只读原生审计指出Desktop无任务栏按钮却仍创建并释放ITaskbarList3，现仅DESKTOP跳过不需要的同步Explorer进度COM（普通窗/触控手势/OLE不改），作为有依据的隔离收尾；新增回归，待最终增量验收。

- 最后生产路径审计发现旧host/service夹具在主线程构造helper后残留PMv2，早期DPI挂载PASS不代表原始GHOST PMv1路径；新fixture保留原thread后捕获错配且安全恢复。已实现DESKTOP-only原生DPI创建scope，核实实际Explorer父链、仅临时采用其context、RAII还原原thread，绝不改process或已有NORMAL窗口；动态解析系统API避免SDK目标guard。新编译PASS，原始DPI路径已真实挂载并保护capture/Node框选，继续更正hover夹具过严的old=True前提，不放宽真实交互守门。关键桌面状态/错配错误补简繁翻译。

- 发布使用说明保存为blui/README-BLUI.txt（UTF-8无BOM），随源码与便携包提供：明确桌面启用/恢复、Win10双屏验收、Win11/历史托盘边界、条件休眠和不更换Shell；保留旧包。实际桌面service菜单操作/双次复用/缩略图与条件bpy电源菜单均PASS，悬停被动tip实际回调/截图/清理PASS；当前522纯回归PASS。

- 发布allowlist补通知兼容边界说明NOTIFICATION_COMPATIBILITY.md，明确Win10真实Toolbar回调与Win11/XAML公开入口不同；不把DISPLAY-only历史项或纯mock称作全部系统兼容。

- 当前520项纯回归全部PASS。桌面host真实双屏全部PASS（挂载/序号ack/正常restore/OWN helper死亡第二guardian恢复），不是DPI拒绝分支；原ListView本来hidden所以保持原状态，未擅自显示。任务栏真机完整reserve夹具PASS，确认原系统位与两屏work/visibility均恢复，任务栏最终40px原预留、BLUI56px不叠加。
- 开始菜单文档补条件休眠/确认/清醒时间deadline；打包allowlist补DESKTOP_HOST.md。新包另起目录，保留所有旧发布包，不覆盖。

- 休眠超时改用独立worker内QueryUnbiasedInterruptTime计量60秒清醒时间，避免长时间休眠后刚恢复就误杀自身helper；普通任务deadline保持原monotonic，UI/draw无系统API。参考Microsoft官方awake-time契约，纯mock测试不执行睡眠/休眠。

- undo/load/unregister共用cancel路径补notification_hover.close，精确清理自有被动tip且真实LEAVE只发一次；vendor tooltip保持原文。桌面宿主恢复SetParent(NULL)中间WS_CHILD校验早退已由host子模块修复，最终style/owner/instance校验仍保留，待真机复验。

- Reserve全生命周期夹具增加逐phase实际耗时诊断，90秒全流程上限（非UI等待，交互进程继续消息泵）；各PASS仍要求真实work/state/visible恢复，不以放宽断言替代恢复。上轮guardian退出后已确认两屏原工作区1400、两原栏visible=True、原state0，日记无剩余项。

- 桌面原生实际7秒回归通过：初始隐藏/独立instance、真实子窗焦点与Node键盘选择、父窗死亡仅回收自有临时layout、正常Node保留、save/open不泄漏桌面UI；真实截图正常。首次键盘失败定位为夹具event_simulate默认(0,0)，修正为真实区域坐标，未改弱化原生守门。
- 通知tooltip独立被动窗集成：普通任务选择Panel排除NOTIFICATION_TIP，防止提示和设置混绘/挤压；不改正常选择窗焦点。

- 真机 reserve 首轮证实释放原Explorer预留后work=[0,0,2560,1440]，自有AppBar仅保留56px（底部1384）；explicit restore等待超时，退出独立guard后物理原栏状态/工作区完全恢复。夹具加入变更时诊断，继续定位等待，未记为整体通过。

- 新增休眠菜单真实draw AST回归：开启/关闭能力的两支显示与INVOKE_DEFAULT确认路径；draw禁止任何Windows能力查询，只读异步RAM缓存。首次桌面宿主QA超时，但其独立守护恢复日记已确认为 shell=null/canvases=[]；继续修协议/实际UI交互，未把失败算通过。

- 用户确认以本机 Win10 19045 为主要验收环境；Win11 分支只记录源码/协议回归，不冒充实机完成。只读真实托盘 bootstrap 修正 COM 激活上下文后 READY、44 UIA 条目、18 真实图标像素；继续核验非应用条目过滤与实际回调。
- DESKTOP 进一步隔离：不允许任务栏 close/topmost/context helper 触碰桌面，保留 Node 原生右键/拖动；桌面替换设置入口与新增通知系统控制文本加入简体/繁体本地化。原生第一轮编译已启动。

- 新DESKTOP原生角色与GHOST flag：独立borderless/tool但可交互的Node窗，不套INFO菜单、不NOACTIVATE；modal守门按正常Node窗口保守处理。仅桌面child的WM_SETFOCUS/KILLFOCUS转活跃事件，标记宿主被原父毁窗时原生handle置失效并排队关闭，禁止在WM_NCDESTROY直接释放GPU/Area。生命周期尚在集成/未构建验证。
- AppBar原生ABN_STATECHANGE也递增generation，让隔离guard释放/恢复原reserve后立即重query；其它窗口和系统Z序不变。

- 桌面宿主子系统开发：已核验 Lively 最新 core-separation 的 Win11 raised/24H2 层级与 Microsoft SetParent 契约。采用 interactive canvas 作为实际 Progman/WorkerW icon-host 的直系前置 child，仅暂隐原 SysListView32，不改 Shell/壁纸/Explorer 进程或外来 Z 序；不同 DPI awareness context 拒绝跨进程 parenting，原系统桌面保持可用。
- 新 desktop_host_state 独立有界模型与 journal-before-mutation 全屏事务，保存原窗口样式/owner/physical rect 与原 ListView 可见性；恢复使用 PID/thread/start/class 和父链精确身份，显示器变更/窗口丢失回滚并标记需重新连接。原生 DESKTOP role5 / WM_NCDESTROY 安全清理由主代理接入；子代理不运行真实桌面接管。

- desktop_host_native 新增 helper-only 正式 Explorer 路径/进程启动身份、Progman/WorkerW→DefView→SysListView32 直系且唯一链校验、DESKTOP 专属 marker、精确 DPI context 相等检查与 parent-client 物理坐标映射；只改本 BLUI canvas 的 parent/style/sibling Z，原图标已被用户隐藏时不擅自显示。Win11 raised 分支只为自身 child 增加 layered，需主代理原生验证，不能宣称 Win11 实测。

- 新 desktop_host 非阻塞 RAM facade、desktop_host_watchdog 隔离 parenting 服务及 desktop_host_recovery 第二守护进程：副守护先 READY 才允许接管，EOF/owner death/UI 心跳丢失先恢复原图标、再恢复精确身份 canvas；主 helper 挂死或被终止时副守护通过独立心跳/内核 process handle 恢复 journal。每代 nonce 命名 abort event 和 journal 校验避免旧守护干扰新宿主；不强杀进程，UTF-8 协议，CLI 在恢复完成后才退出自身。

- 副守护持有只读 SessionWitness mutex handle 直到恢复完成，防止主 helper 已退出而新宿主抢先覆盖 journal，与旧副守护产生代际写入竞争；guard 的 nonce 检查仍作为第二防线。native 专用 DESKTOP class/no-OWNDC 支持由 window_hover_previews 子代理接入，host allowlist 将同步其精确类名。

- Native 子代理确认 DESKTOP 专用 `BLUI_DesktopWindowClass`（无 CS_OWNDC），host exact class allowlist 已同步，同时保留 GHOST legacy + marker 双约束。新增 test_desktop_host 纯事务/协议/native mock 夹具：日记前置/半挂载回滚/原隐藏状态/nonce隔离/监视器失效/重用HWND/父链改动/DPI不匹配拒绝；未启动任何 helper 或 GUI。

- desktop_host 24 项纯回归已实际 PASS（2026-10-13）；DESKTOP_HOST.md 记录用户 opt-in、全显示器 descriptor API、原桌面恢复、Win11 raised 边界、DPI拒绝与 native parent-destroy 契约，链接 Microsoft/Lively primary references。子代理没有运行桌面宿主、接管原桌面或 GUI。

- 与 native 子代理同步追加 `BLUI.DesktopInstance.v1` 每 ctor 单调非零 token：journal 记录且每个自有 canvas mutation/restore 均核对，覆盖同一 PID/thread/class 内 HWND 复用而 process-start 不变的风险。固定 role marker 仍=1；新增第25项 same-process recycled HWND/new-instance 禁止恢复测试，待复跑。

- Host UI/服务协议补 `completed_serial` 实际 transaction ack：reconcile/restore 返回递增 serial，helper 仅执行完成后发布；初始 empty/restored 不代表新 restore 已完成。Root disable 需 ack+pending_restore=False 才销毁自有 DESKTOP。停止状态的 facade.restore 可按同目录新建 guardian 恢复 journal，但前代锁未释放时严格拒绝并不覆盖旧 journal；新增对应纯回归。

- 最新 desktop_host 26 项纯回归已 PASS。新增主代理专属 check_desktop_host_native：必须显式 QA env opt-in / disposable CONFIG，创建全屏自有 DESKTOP、实际 helper ack+恢复、仅终止本夹具 kernel身份 child 以测第二守护；DPI不符必须证明原ListView未变并记录 fail-closed，不冒充 rendering PASS。不发Win+D影响用户窗口、不杀Explorer、不改普通Canvas。子代理未运行夹具。

- Native 夹具 crash阶段不能等待已死亡 helper 的 RAM pending_restore 更新，清理改读本夹具精确 journal 已空且核验原ListView/自有canvas物理脱离；正常 restore 阶段仍严格使用 completed_serial ack，不跳过生产服务生命期断言。

- Host review 补严格 Progman host 必须等于 GetShellWindow root、capture 完整记录后再次核对 canvas instance/role marker/host父链，拒绝快照期间更换窗口；新增第27项相应纯回归。

- 最终宿主子模块纯回归 27/27 PASS，主代理 native 夹具 AST syntax PASS；仍未启动实际 desktop host 或执行桌面接管。验收必须区分实际已挂载与 DPI mismatch fail-closed，后者只证明原桌面不受损，不能代替桌面功能验证。

- 桌面宿主接入胶水新增 desktop_service/desktop_ui：默认不启动接管；explicit ENABLE 先恢复前代 journal、等全显示器 fresh topology 与布局 profile restore，再建专属 DESKTOP Node 窗并复用 monitor board。disable 必须 serial实际ack + !enabled + !pending_restore 才关闭本 service 所有桌面窗口，普通 NORMAL Canvas 不动；拓扑变更先恢复、等待新隔离 monitor snapshot，再同步/重建。
- runtime 仅新增 service生命周期小段：末尾在所有旧live-area消费者之后执行自有窗口开闭并fresh redraw；undo/redo cancel_pending 安全脱离且不关闭canvas，load_pre/unregister关闭独立host由双守护恢复。displays普通placement排除DESKTOP，显示器菜单和新operator给出显式连接/恢复入口，新增UI均iface本地化，词条由主代理接。

- 主代理首轮 desktop-host 原生夹具50秒 timeout；只读审计唯一 retained QA journal已空、无残留desktop_host helper/recovery。当前原ListView IsWindowVisible=False，但首轮日志未记baseline，不能据此断言异常隐藏；未做恢复写操作。夹具补baseline、每窗DPI/context/token以及phase/issued/completed/status/helperpid/poll/stopped完整诊断，供主代理串行复跑定位，不隐藏timeout失败。

- 夹具 review 发现 own-helper crash 恢复完成后，若client尚未观察EOF，cleanup可能向已死helper发送restore并等待永远不会有的serial ack；crash阶段现在明确以第二守护journal完成信号进入清理，不再给dead stdin发命令。接入service load_pre先shutdown、commoncancel随后执行时增加CLOSING防重启保护，关闭中RAM状态继续收尾，避免load预钩子意外重新接管。

- 新 test_desktop_service 纯FakeHost/FakeAdapter夹具覆盖默认无接管、实际ack/fresh snapshot/profile等待、modal守门、undo不关窗、workarea/热插拔恢复先行、丢失native token仅重建缺失屏、半创建故障已记owned后恢复、DPI拒绝、load-pre与commoncancel顺序、防job admission满队列丢layout；未导入bpy或启动helper。DESKTOP_HOST.md补胶水生命周期和UI接口说明，待执行。

- 主代理第二轮真实两屏 DPI context34相同，serial1 actual attached2，serial2已消费但restore pending。核对 Microsoft SetParent(NULL) 后需再清WS_CHILD的契约：中间GetParent可为Desktop HWND，旧 helper 误判早退而跳过样式恢复。修为NULL detach仅按API错误判断，清原style后最终精确owner/style/exstyle验证；重试仅允许原已验证host或官方GetDesktopWindow，不接受任何任意foreign parent，instance/PID/thread身份不放宽。追加2项纯回归及owned rollback详细读诊断，待主代理复跑。

- 第三轮真实诊断 parent/style/exstyle/owner已复原，但rect仍挂载大小，怀疑跨进程GWLP_HWNDPARENT无变化写入拒绝并被catch吞掉。恢复现在跳过已完全相等style/exstyle/owner的写入，必要写失败记录具体WinError/index；最终仍精确验证所有原状态，并新增ASYNCPOS物理rect待消息循环完成的有界pending重试，journal不提前清空。主代理上一轮退出后的唯一journal已空；子代理仅只读检查，没有恢复写操作。

- 主代理第四轮 desktop host 原生完整 PASS，5.85秒：真实双屏DPI34相等、attach2/serialack、原style/owner/geometry恢复、再接入、仅终止本QA helper后第二guardian恢复。baseline原ListView已隐藏且退出保持隐藏，未将Win10结果冒充Win11/Win+D实测。DESKTOP_HOST.md已记录，DESKTOP.md旧“无AppBar/不协调autohide/没托盘UWP”说明同步为当前机制与边界；酷呆仅公开README行为参考、自行原生Frame/文件服务，未声称源码移植。
- 新主代理专属 check_desktop_service_native 真实UI胶水夹具：实际ENABLE/RESTORE Operator/Runtime，自己的两PNG目录走真实scan/缩略图worker，全屏树的monitor与Node保留/第二次启用复用、NORMAL窗口不改、ack后own关闭、原ListView恢复；另实际bpy Power Menu.draw只录制conditional Hibernate条目和保存警告、不执行电源动作。子代理未运行。Service追加restore后的异步最终布局save-tail（存储失败不阻挡Windows恢复），闲置时仅RAM heartbeat避免已启动guard误报失联，不启动默认接管。

- 主代理 desktop_service 实际GUI全PASS，7.8秒：真实operator双屏两轮ENABLE/RESTORE、own PNG异步preview、每屏Node/monitor绑定、FakeUser board/layout复用、NORMAL screen/area/window不变、实际restore ack后关闭自有源、原ListView基线保留、Hibernate条件Menu/确认文本仅draw通过，无真实电源动作。Host纯30+service纯15 PASS；DESKTOP_HOST.md已同步实际验收。
- 原生专用 `blui_has_desktop_interaction` getter与RNAWindows.busy唯一小段已交 window_hover_previews 子代理，解决普通hover导致接入/关闭误判永久忙；旧Node数据全局guard不放宽。我已冻结其他Python接入源码，不再重构；后续主代理串行复验/打包。

- 用户授权继续完善并在验收后打包提交；保留旧shell-redesign发布包和所有用户运行进程，用户自有check_navigation.py/.cmd不纳入提交。
- 本机只读确认Windows10 19045，Win11特有路径需要版本分支/mock与后续Win11实机验证，不能把Win10回归说成Win11全量实测。
- 酷呆官方公开repo目前仅README，无实现代码可直接移植；行为参考盒子分组/文件夹映射，桌面宿主由BLUI自行接入，仍不换系统Shell/不杀Explorer。
- 新worker-only SYSTEM_POWER_CAPABILITIES检测S4+完整hiberfile；Start后台30秒缓存，已开启休眠才显示“休眠”，确认后worker再次检测并调用SetSuspendState，不运行powercfg启用休眠、不关闭唤醒事件。GUI/实机检测待验证，测试禁止真实休眠/关机。
- 发现上一轮client.Job admission表遗漏start_location和taskbar_settings load/save，虽worker和response已接但真实请求被拒；本轮补齐严格参数验证并补实际IPC回归，避免只mock持久化而遗漏入口。
- 新power纯夹具验证SDK布局76字节、S4/hiberfile FULL条件组合、检测不执行电源动作、确认/保存提示、执行再校验与唤醒保留、缓存single-flight/失败隐藏与关闭取消；所有休眠/关机API均mock，待执行。
- 9项power纯测试已PASS。新增READONLY真实helper power检测与OWN临时任务栏设置load/save/readback夹具，及client/worker admission表精确一致的AST回归，避免遗漏已实现请求。Hibernate job等待上限60秒，resume后先读result、不禁唤醒事件；实际电源动作仍禁QA执行。
- 实际隔离power/settings IPC已PASS，本机hibernate=True、OWN临时JSON设置load/save/readback正确且无BOM，完全未执行休眠/改配置。Desktop从taskbar helper枚举/关闭和shell-only modal守门隔离，仍纳入正常Node守门；系统栏reservation状态变更触发monitor重读和RAM AppBar.invalidate。

## 当前验收：2026-10-13 shell-redesign

- 原生 Release 构建通过；382 项纯回归通过，日志 `D:/BlenderUI/build/shell-redesign-unit-release.log`。
- Open-Shell 风格双栏、原生独立滚动/程序目录、开始/应用右键窗、两源 DWM LIVE 悬停、ESC/父子保活、原有 left/middle/Shift 操作通过真实窗口回归；滚轮不改 DPI/View2D zoom。
- 私有真实通知接收与 UI 全链路通过：8图标/透明缓存、native LEFT/RIGHT版本4回调、独立overflow、删除与退出恢复。此验证不广播/接管用户系统通知，不能声称 Win11全量托盘兼容。
- AppBar真实56→80预留与最大化避让、全屏降层/物理定位不升层、退出恢复通过；6组栏高/图标/1x2x像素和Start左/app中布局通过。自有辅助角色三轮保存/重载隔离通过。
- 本机Calculator安装包真实AUMID资源经隔离原生解码为256×256；Programs快捷方式索引正常。直接AppsFolder索引尚未接入。
- 编译EXE SHA256：`44DD2AB85CEA6DD6DC892CE8880049844B23D68A6198D1CB7403E58840E0B3FA`。
- 新便携目录与 `.zip` 已保存至 `D:/BlenderUI/dist/BLUI-1.0.0-windows-x64-20261013-shell-redesign`；allowlist复制3826运行文件、无陈旧文件，另附5说明与README。ZIP共3832文件、125649902字节，逐文件CRC完整通过、必需runtime/helper/新增模块齐全且无PDB/pyc缓存。成包本体原生菜单/右键/滚轮/DWM综合回归PASS（`portable-shell-redesign-native.log`），EXE与build哈希一致，不覆盖旧版、不结束用户实例。
- 最终build本体菜单/通知UI/AppBar/旧任务栏交互串行复跑全部PASS，日志 `D:/BlenderUI/build/release-check_*.log`；AppBar夹具追加物理定位不重新升全屏Z序的真实断言。
- 兼容边界：原系统栏显式隐藏只改可见性、可能仍有预留空带；跨BLUI进程栏未全局去重；不响应TaskbarCreated的历史图标和部分Win11系统控件未镜像。保留系统栏恢复入口，不声称完整替代Explorer。

下方“开发中/待实测”段落记录实现时序，以此验收段和后续成包记录为当前状态。

## 2026-10-13 Win11 通知区兼容性补强（新轮，开发中）

- 冻版文档同步 `NOTIFICATION_TRAY.md` 与新 compat 说明：移除“既有历史图标无法镜像”的旧结论，说明 bootstrap 不依赖重新登记、系统 controls/平台/能力协议兼容扩展、真实 RGBA/诚实降级与 on-demand 未实测边界；Win10 实机证据不作为 Win11 全量兼容承诺。

- Root 最终 OWN 原 Explorer 夹具全 PASS（约9.8s）：真实 LEFT/RIGHT/DOUBLE/ENTER、LEAVE 原控件 delivery/不造 App callback、OWN icon 删除。安全收尾：OVERFLOW RIGHT/DOUBLE 不主动折叠，LEFT 也须打开后的 foreground HWND+创建身份未改变且无用户输入变化，避免关闭刚打开的 App 菜单/抢焦点。公开 auto-hidden on-demand 路径尚无实机 end-to-end 证据，文档保持 PARTIAL，源码/API/label 冻结。

- Metadata bounded diagnostic 只旁路记录，不改变生产是否接纳 icon；debug map 达上限也不使新增真实项因 KeyError 被丢弃。

- Root 最新 OWN 图标未进 bootstrap，新增 solely OWN `Shell_NotifyIconGetRect` SDK 只读登记确认与 bounded metadata stage（不传 wire、不输出别的 App 路径/像素），定位 owner/path/CopyIcon/缓存枚举过滤原因，不以时间重试或假回调掩盖失败。

- 通知兼容性文档补入 Win10 OVERFLOW 明确点击语义与守门、恢复范围；协议新增 click-only Win10/no-guessed-callback 纯回归。仍保留 PARTIAL 标记，不把待验的 on-demand 路径写成全量兼容。

- OVERFLOW 新增元数据/唯一目标守门纯回归；Root OWN 原生 fixture 支持显式测试自己的隐藏项（仅 OWN tip+当前身份）、公开 Chevron Invoke 后 fresh Toolbar hover 与恢复本次 dropdown 状态，UNSUPPORTED 仅输出小元数据、不输出 RGBA。

- Root 只读证实 Win10 Chevron：实际 Button/AutomationId1502/原生ControlID1502/Invoke，非 ExpandCollapse。显式点击历史项才可走 OVERFLOW：逐项验证真实 App HWND+UID+GUID+创建身份/当前元数据，公开 Invoke 原 Chevron 后 fresh 枚举，只唯一精确 tooltip/原 Toolbar 目标才代理；不改偏好或长期显示原栏。只关闭本次打开的相同 dropdown，实际用户输入改变则保留用户状态；不猜 App callback/version。

- 准备用户点击历史项才临时展示原 overflow 的安全方案，新增 Root 只读 `check_notification_controls.py` 获取实际 Chevron UIA/原生 class、AutomationId、ControlID 与 ExpandCollapse 语义，不先猜 Explorer 私有按钮 ID，不执行任何 Invoke。

- Root 真机 OWN callback 证据：LEFT=[0x201,0x400]、RIGHT=[0x204]、DOUBLE=[0x203,0x400]、HOVER_ENTER=[0x200]；LEAVE 送达原 Toolbar 后 Explorer 无 App callback，是其实际语义，不伪造。夹具改验证原控件成功 delivery 并记录空 callback，文档明确与直接 NIM 的保证不同。

- 只读 glyph probe 最新 24 项全有真实像素（23 个去重 digest；5 Toolbar/19 DISPLAY），无圆点。UIA 在验证过的通知根内改用 RawViewWalker 尝试读取已存在但隐藏的 overflow provider，仍受节点/深度/时间边界；不会开窗口或改图标设置，是否额外支持取决于真实 Explorer 暴露情况。

- 正常 App 与固定系统入口去重仅在真实系统 GUID + 原 Explorer PID 可证明时执行，不猜 tooltip 所属 App。匹配到真实系统 Toolbar 时 LEFT 走该实际原控件；其他情况下保留固定系统 fallback，不按名字猜 callback。

- Glyph fallback 的 RECT 比较显式逐字段，避免 ctypes Structure 误当 iterable；前景 HWND 非零但无法验证身份时拒绝抓取，保持 fail-closed。

- 按 Root 许可新增原 Toolbar-only `PrintWindow` glyph fallback：只留存精确 UIA 按钮裁剪，Foreground/根/Toolbar/overflow 祖先/矩形前后核验；不读桌面或任意 App 内容、不移动/显示/激活窗口。真实 HICON 优先，无法确认统一背景或无实际 glyph 时拒绝，不将全黑/圆点算成功。原控件 16/24px fallback 不冒称复原 32px 原 HICON。

- Root 真实 OWN Explorer fixture 已走到 hover-leave，前面 LEFT/RIGHT/DOUBLE/hover-enter 均收到实际 App callback。直接 WM_MOUSELEAVE 不产生 leave 回调，现先把原控件的逻辑 hot point 移到 client 外（普通 WM_MOUSEMOVE(-1,-1)，不动真实光标/不点击相邻项）再 leave，让 Explorer 自己清理 hot item/NIN_POPUPCLOSE；fixture 逐事件打印消息供 Root 再验。

- Root path_failure 全量异常定位到 bounded LPWSTR 读函数：ctypes WCHAR 的 `\0` 在 Python 是非空字符串，不能用 truthiness 判断结束。已显式比较 NUL 并新增自有内存纯回归，避免越过 COM 字符串终止符；路径 native API 本身无需猜测或放宽 owner 校验。

- Root OWN fixture 的原 Explorer ADD 被私有简化 wire 拒绝，已改用 SDK 原生 `NOTIFYICONDATAW` + `Shell_NotifyIconW`，不尝试未知多格式报文。调用前须验证第一 receiver 就是已核验原 Explorer，避免误投用户现有 BLUI host；x64/32 ABI 分别 976/956 字节，Shell32 自行负责跨进程签名与 WOW64 marshalling。

- Bootstrap 可只读发现当前已存在、同 Explorer PID/创建时间的 Win10 `NotifyIconOverflowWindow`，不展开、不改变可见性；其 Toolbar 若公开有效 UIA 元素/矩形可走同样真实输入代理，额外逐条核验 overflow 容器身份与祖先关系。无窗口或未公开元素仍明确 DISPLAY-only，不改全局图标偏好。

- 聚合 diagnostics 区分 known-folder/path API 失败与真实 exe 失配；bootstrap 包含 DISPLAY-only 或仅 default-action 项时明确标为 PARTIAL 并提示原系统通知区，防止把“可显示”冒充“全行为支持”。

- Root 检出朴素 exe 路径比较误杀 38 项，新增独立只读路径适配：解析 Explorer `{KNOWNFOLDERID}\\relative.exe`、环境变量、NT prefix/本地 short path，再与当前 PID executable 比较。路径不成为命令、不查询任意 UNC，native probe 仅输出路径形式聚合统计，不输出用户安装路径。NOTIFYITEM x64 ABI 与 ManagedShell 定义一致（56 字节，guid offset40）。

- 第二次只读 native probe 已取得真实 HICON（18 个去重 digest），也暴露 `ITrayNotify` 持久偏好/ghost 条目。COM 适配补充当前 HWND/PID executable 与 pszExeName 精确匹配，并仅保留有可复制 HICON 的活跃记录；零 HICON/失配路径/像素失败分类统计，native probe 输出 diagnostics，不把 ghost 圆点当成运行中 App。

- 基于真实 Win10 probe 收紧历史 App 托盘范围：仅实际 Toolbar 或已识别 NotifyIconStack/NotifyIcon 子树，不把 V 形展开、原系统时钟、显示桌面等按钮当成普通 App 图标；固定系统入口单独处理，避免重叠时钟/通知按钮。

- Root 只读 native probe 已读取 Win10 19045 的 13 个历史 provider，其中 5 个具真实 Toolbar 代理能力；像素为零且 COM 报 0x80040154。定位为 optional ITrayNotify 错用 UIA 的 INPROC 激活范围，已改为 Explorer LOCAL_SERVER（不启动任意 executable）；需 Root 重跑验证 HICON。

- `blui/NOTIFICATION_COMPATIBILITY.md` 保存主流 Apache-2.0 源码与 MS/SDK 依据、真实 CALLBACK/Win10 Toolbar/UIA default/DISPLAY-only 能力区分、系统 fallback 和 Root 原生验证范围。不将 Win10 或纯 mock 证据说成 Win11 完全兼容。

- 通知纯测试扩至 62 项通过；补强异常输入类型验证，避免 malformed JSON key/event 造成 helper TypeError；UIA COM 构造失败也进行对称 Release/CoUninitialize，不遗留 apartment 引用。

- 系统按钮测试缓存 stub 跟随生产 RAM cache 规则：无 cache_key 的系统入口使用原生主题 glyph，不错误返回 App 自定义 preview ID。

- 通知纯 UI fixture 加入独立本地化 stub，验证系统入口图标与宽度以及历史 provider 能力说明，不依赖终端加载 Blender `_bpy`。

- 新增 Root 专用 `check_notification_history_native.py`：只向身份验证过的原 Explorer 注册一个唯一 OWN-PID 测试 icon，在其已存在后 bootstrap，尝试原 Toolbar 的 LEFT/RIGHT/DOUBLE/hover，再删除这个 OWN icon；不广播、不改 auto-tray、不猜 App 消息或触发别的应用。自动隐藏或未公开 provider 时输出 UNSUPPORTED，不伪造通过。系统入口与历史能力 tooltip 新增纯 UI 回归。

- 新增回归后托盘 60 项纯测试通过。Toolbar 代理进一步要求快照与 action fresh 的完整按钮矩形、Toolbar HWND/thread 一致；输入前排除同 Toolbar 中心覆盖的歧义按钮，矩形变化则明确要求重试，不点击猜测位置。

- 新增纯 bootstrap/版本/能力/SDK ABI 回归与 Root 专用只读 `check_notification_bootstrap.py`：读取真实 Explorer UIA/COM 元数据但不启动托盘 host、不加图标、不广播、不调用图标、不改系统任务栏或输入。原 43 项托盘纯测试已通过，新回归与 Win10 真实 bootstrap 结果待记。

- 根据本轮“以 Win10 为主”补充原通知 Toolbar 的本地输入代理：只向实际 Explorer 托盘子树内 `ToolbarWindow32` 发送普通 mouse 消息，让 Explorer 使用自身真实 notification callback/version；Root/Toolbar 身份逐条重新核验，UIA fresh RuntimeId/名称/矩形与 client 内边界需匹配，超时 250ms。没有 TB_HITTEST 指针跨进程误用，没有鼠标移动或猜测 App callback；Win11 不启用该分支，尚待 Root 原生 fixture 验证。

- 系统 LEFT 优先调用经身份与托盘子树验证的 UIA 系统按钮（控制中心/输入指示器/通知中心/时钟）；找不到提供者或版本失效时才使用固定 Windows 快捷键/设置页。POWER 的无提供者 fallback 是电源设置，INPUT 的 fallback 是 Win+Space 切换输入语言，不把 fallback 描述为完全等价的原生弹窗。

- 通知 UI 增加可本地化的系统入口，尺寸仍由 `logical_width()` 统一预留；历史图标能力不足时在高窗显示恢复 Windows 通知区入口。恢复按钮只请求现有恢复服务，不向尚未显示的 Windows 托盘即时注入 Win+B。真实回调 hover-enter 改为 WM_MOUSEHOVER（与 NIN_POPUPOPEN 一起），不误充 WM_MOUSEMOVE。

- 托盘 wire 保持旧 5 字段快照兼容，并新增 platform/controls/bootstrap 与 CALLBACK/UIA/DISPLAY 能力声明。UIA 行严格拒绝冒充真实 callback/version，RIGHT/DOUBLE/hover 不支持时明确失败。Host 接入后台 bootstrap 与固定系统入口，QA private 模式不扫描 Explorer、不暴露系统控制；Win11 已知系统图标 GUID 使用固定入口避开旧回调风险。

- `notification_history` 增加有界、独立线程的 Explorer provider 扫描：RuntimeId token 绑定进程创建身份，仅在托盘子树读取可用按钮；LEFT 调用前重新扫描、核验根窗口与 RuntimeId。无 Invoke/default-action 的历史元数据明示 DISPLAY-only，不把同名图标当作操作身份；helper NIM 消息泵不执行 COM 查询。

- 历史托盘读取新增 SDK ABI 最小 UIAutomation 客户端和可选只读 `ITrayNotify` 元数据适配，所有 COM 查询将限定在通知 helper 的后台线程；每个返回接口和 SAFEARRAY/BSTR 明确释放，UIA2 设置 300ms provider 超时。未调用全局 UIA 搜索、远程内存写入或 Explorer 显隐设置。COM 元数据只用于图标像素补充，绝不猜测其缺失的 callback/version。

- 核验当前 ManagedShell / RetroBar 主源码：两项目均 Apache-2.0；历史 bootstrap 依赖旧 ToolbarWindow32 与远程内存，ITrayNotify 的 NOTIFYITEM 不含 callbackMessage/version，Win11 无 toolbar 时不能据此制造可靠回调。本轮仅独立重写机制，不复制或链接代码、不临时改变 EnableAutoTray。
- 新增固定系统入口模型与 helper-only 执行器：网络、音量、电源、输入语言、通知、日历和原系统区；Win11 使用公开快捷键/URI，旧系统音量用绝对系统目录 sndvol；右键/双击入口转对应固定设置。系统快捷键注入前拒绝已按住的修饰键，部分失败仅释放本操作可能按下的键；私有测试禁止真实系统动作。
- 本机实际 Win10 build19045；Win11 机制只能做源码/版本 mock 与边界验证，不声称 Win11 全量实机兼容。后续新增隔离 UIAutomation 历史桥，不将 Explorer HWND 传入任意应用激活接口。

## 原生 UI 悬停与真模态状态区分（2026-10-13，本轮实际GUI修复）

- 实机发现任意 WM_HANDLER_TYPE_UI 都被认为忙，普通按钮悬停/延迟移除也会阻挡
  开始菜单异步RNA列表更新及任务栏悬停预览。新增只读 UI_handler_has_modal_interaction，
  通过真实callback/remove身份确认userdata类型；先识别DO_FREE，不解引用已释放button data。
- 仅shell role的HIGHLIGHT/EXIT可继续服务；文本/数字编辑、等待释放/拖动、popup、searchbox、
  custom interaction和未知UI callback保持阻塞。Normal Node/Canvas原有保守守门未改变。
- 主代理将仅操作私有INFO/shell RNA的服务改用shell-window scope；Node结构/背景/缩略图
  继续原有全局守门；图标job admission只读RAM队列并隔离提取，不被无关hover阻挡，不削弱节点指针防护。
- 状态分类附编译期断言，新增5项source安全回归，约束callback类型确认/DO_FREE提前检查、
  popup/search/custom交互保守、Normal守门不放宽；真实GUI行为仍由主代理编译后回归验证。
- 新7项shell scope纯回归通过AST提取实际runtime守门函数，未导入bpy或启动GUI：
  NORMAL忙只阻挡文档/节点服务，不阻挡独立shell列表；所有shell role的真实held交互
  仍阻挡；无shell/空窗口/闲置shell为false，且shell检查不读取无关NORMAL模态RNA。
- 新 check_taskbar_appearance_ui.py 仅交主代理串行运行，子代理未运行：真实RNA尺寸控件
  32/16、80/64、160/64各在user UI scale1/2回归栏高、实际图标像素和Start左侧独立布局；
  图标由真实隔离Job加载本程序，任务列表仅本PID单窗，禁AppBar/系统栏/通知区接管，
  仅launcher被拦截；独立截图阈值不改旧32px像素夹具的默认断言。

## 可调任务栏尺寸与原生最大化避让（2026-10-13，本轮集成中）

- 新 taskbar_settings 模块提供栏高32–160、图标16–64逻辑像素设置，默认56/32，
  高度至少为图标+16。RAM变更通过隔离worker异步持久化，沿用原子写入、锁和有效备份，
  修订号防止旧请求覆盖新值；load/save进行中再改尺寸会合并而非丢失。
- 新 taskbar_appbar 模块仅为 BLUI 自有 TASKBAR HWND 注册 Windows AppBar，
  QUERYPOS/SETPOS 返回系统认可区域，让最大化窗口尊重任务栏；保留原系统栏时遵守其
  现有占用，多显示器负坐标/DPI分别计算，不写 SPI_SETWORKAREA 或改其他应用窗体。
- 主代理接入 callback 0x82A7、实际定位/关窗/加载清理及 UI 设置；独立模块在每次写操作
  前复核 PID/线程/进程创建时间/窗口类，回收时不碰复用 HWND 新主人。说明见
  blui/TASKBAR_APPBAR.md；原生实际注册验证仅由主代理在自有夹具中进行并及时释放。
- 尺寸设置8项、AppBar13项纯 mock 回归通过；连同DWM和既有任务栏模块共92项回归通过，
  diff格式检查通过。AppBar只在系统认可区域变化时发SETPOS，位置变更另发ABM_WINDOWPOSCHANGED。
- 原生 GHOST TASKBAR-only WndProc subclass接入0x82A7：位置通知仅递增generation，
  全屏通知只降低/恢复自身Z序（不激活），TaskbarCreated递增restart使Python重发NEW；
  WINDOWPOSCHANGED/ACTIVATE通知Shell，有原生重入保护，无回调中QUERY/SETPOS循环。
  新 HWND property token补强同进程句柄复用，销毁前原生移除登记作为Python清理兜底。
- AppBar原生通知适配后的18项纯 mock 回归通过；补充重启重登记、全屏/epoch读取、
  marker安装失败和其他控制器marker保护。原生全屏重入恢复之前guard值而非直接清零。
- AppBar按原生generation/restart/fullscreen、完整监视器几何/DPI、逻辑尺寸及窗体身份
  缓存认可区域：状态不变的服务tick不再进行任何Shell串行IPC；通知变化只重新query一次，
  记录SETPOS之后generation避免自通知循环，新增相关纯mock回归。
- 新 check_appbar_windows.py 交给主代理串行运行，子代理未运行：隔离配置/禁止自动系统栏
  控制，在本进程新TASKBAR上真实预留56→80逻辑像素、验证自有NORMAL最大化避让、
  自有原生通知/全屏Z序及工作区恢复；失败/45秒超时先注销再销毁自己的bar，不操作外部窗体。

## 进行中：真正的双栏开始菜单、任务栏交互与系统集成（2026-10-13）

- 用户实测指出旧开始菜单未符合Open-Shell，右键/tooltip被薄任务栏裁切，滚轮误缩放。
  同时要求UWP图标、可调栏高/图标大小、独立开始键、系统托盘和窗口避让，本轮合并处理。
- 子模块并行实现开始菜单原生UIList/程序层级、隔离包图标、DWM直播缩略图、AppBar/配置、
  隔离通知区协议；主代理负责原生事件隔离、独立popup、整合、构建、实测及打包提交。
- 新增TASK_PREVIEW不激活的独立角色；shell区域移除INFO通用缩放和帧键位，面板锁定zoom。
  通用live按钮上下文区分当前按下事件和悬停坐标；shell文本操作项左对齐，任务栏关闭被裁切
  的内置tooltip。可变尺寸任务栏以实际布局居中，默认组件不变。新启动项文件位置动作接入IPC。
- 尚未构建/实测，不能将源码集成视为已完成系统托盘或窗口避让。
- 新增独立shell_context_ui与shell_hover：右键截获启动项/任务应用，菜单放独立原生窗；
  悬停350ms延迟显示DWM预览，跨入预览保留、离开延迟关闭，点击卡片走原身份校验激活。
  所有DWM/光标查询在timer，draw仅读缓存。仍待原生布局、滚动和事件实测。
- UWP主UI按AUMID缓存，不再使用共享宿主exe图标；包资源在worker解析后走原生headless PNG
  解码，单包请求限制在独立超时内。任务栏源包含用户可调尺寸；AppBar保留原系统栏时尊重
  已有AppBar，认可区域用自有物理坐标定位，不用已经扣除任务栏的work区再次夹紧。
- 开始键固定独立左侧，任务组可居中/左排；尺寸控件、原子配置IPC、通知区UI与独立context/
  preview classes接入注册及timer。AppBar注册位置常态半秒校正，预览悬停常态100ms服务；
  load/undo/关窗前取消DWM关系和工作区占用，通知区helper退出仅影响本次创建的进程。
- 应用右键动作使用实时身份并通过WM_CLOSE正常关闭，不结束进程或绕过保存提示；启动项
  context Pin后仅关子菜单，Open后关闭同一身份的开始父菜单。通知图标右键转交其原有回调。
- 完整纯回归首测340项通过；通知区OWN私有真实协议、32px透明HICON、负坐标version4回调
  已通过。初测解释器退出被stdin线程锁卡住，辅助进程修复只退出自身后重测完整通过。
  开始菜单/尺寸/context/预览新增词条补充简繁中文；Preview也支持原生ESC关闭。

## 真实通知区接收器（2026-10-13，本轮集成中）

- notification_host / notification_protocol / notification_pixels 分离进程窗体、纯协议
  与图标像素；真实 Shell_NotifyIcon 的 ADD/MODIFY/DELETE/SETVERSION 接收及版本4
  点击/悬停回调，不是静态占位。设计参考 RetroBar/ManagedShell，未复制第三方源码。
- 显式启用广播 TaskbarCreated；仅隐藏的自有接收窗口参与 zorder，通知包有界转发原
  已校验 Explorer。无远程VM、注入、AutoTray/注册表/系统窗口重排或 Explorer 终止。
  父进程原始只读句柄、EOF/关闭清理自身再恢复广播，系统栏保留未重登记历史图标。
- `--qa-private` 私有类单播模式不广播/截获系统消息，用于主代理 OWN PID 验证；
  不等同全量 Win11 内建通知控件验证。主 UI 的 IPC 与按钮接入由主代理整合；
  协议、身份竞态、版本4负坐标、限额及透明像素纯回归见新测试与 NOTIFICATION_TRAY.md。
- 已新增23项纯协议/像素/转发与关闭顺序回归，全部通过；OWN-only check_notification_host.py 原生私有
  单播测试脚本已准备，等待主代理串行运行，覆盖 UTF8、真实 HICON、版本4负坐标及清理。
- 主代理私有真实接收/像素/回调断言已通过，发现 shutdown 后 Python daemon stdin 的
  BufferedReader 锁可延迟解释器退出；已让 reader 收到 shutdown 停读，最终快照有界确认，
  脚本只在自身 HWND 清理/恢复广播完成后自退出。主代理重测完整退出流程已通过；
  中文tip、实际HICON->RGBA、ADD/MODIFY/DELETE、版本4负坐标右键以及私有窗口清理均通过。
- 启动/关闭失败原因保留在最终 disabled 快照，不会被空错误清理状态覆盖。
- 新 OWN-only check_shell_redesign_ui.py 综合原生测试脚本已由主代理串行运行通过：
  原生按钮右键独立菜单、无激活悬停 DWM、80项模拟 Programs UIList 实际滚轮且缩放不变、
  Start-app 子菜单父窗生命周期；仅自有窗/假索引，不启动应用或改变系统任务栏。
  DWM API LIVE 成功登记与 GL 截图分开记录，GL截图不被误称为DWM像素证据。
- 综合脚本UIList插桩保持 draw_item 的8个显式参数；Bpy桥接按 co_argcount 分配参数，
  不能使用变长参数包装而破坏原生回调。
- 综合原生首轮已验证两个独立右键菜单、两条 OWN DWM LIVE 与真实滚轮不改变缩放，
  后续发现fixture持久化 Start RNA 可在外部失焦关闭后 UAF。脚本已全改为跨tick仅保留
  (pointer,HWND) 并鲜查；仅固定 OWN Start 的foreground读取用于wheel/search测试，
  子菜单生命周期检查前恢复真实读取并显式执行生产focus tick，不掩盖生产逻辑。
- 主代理综合第二轮完整通过，包含真实 Start-app 子菜单保活；只读安全review发现的
  预览索引目标错配与源任务栏移除后孤儿预览，均由主代理修复并记录；未扩展为捕获全屏
  或其它用户窗口的“可视证明”，保留 API LIVE/自有菜单像素证据的准确边界。
- 新 preview-click 纯回归通过9项：AST提取真实 invoke，覆盖任务替换/重排/缩短、
  同HWND但PID/线程/启动时间/窗口类改变、缺失目标token与边界点击，确保展示卡片身份
  不被新的任务枚举下标错配；测试不加载Bpy或发送Win32消息。

## UWP 应用真实图标（2026-10-13，本轮集成中）

- 新独立 worker-only package_icons 模块使用 Kernel32 包查询读取当前用户安装包，
  精确匹配 AUMID 的 Application.Id，优先高分辨率 targetsize unplated PNG。
  无 PowerShell、安装、启动应用或主 UI 文件读取；清单/资产有限额，拒绝
  DTD/entities、路径穿越、安装包外资产；缺失或拒绝读取返回中性备用图标。
- ApplicationFrameHost 根窗保留原 HWND/PID/进程启动时间身份，异步枚举进程只对
  明确 ApplicationFrameWindow 查找最多64个 CoreWindow 子窗的复核 UWP AUMID，
  避免不同 UWP 应用误用同一个 broker 图标。歧义、竞态或身份变更不采用。
- PNG 交由已有隔离 File Browser 预览解码器；任务栏 icon_cache 的 AUMID 接口
  由主代理整合。新纯回归覆盖精确匹配、限定资产、尺寸、路径/XML与 broker 身份。
- 已通过21项UWP纯测试；文档约定 targetsize/scale 文件直接有界探测，不依赖大型 Assets
  目录的前512条排序结果，仍不递归扫描包目录；包括 UTF16 DTD 与安装卸载 API 竞态。

## 任务栏悬停预览底层（2026-10-13，本轮集成中）

- 新 taskbar_previews 模块通过可信系统 DWM API 将窗口实时合成到独立原生弹窗，
  不截图、不写磁盘缓存、不载入 Shell 扩展、不操作来源窗口。由主代理接入悬停及窗体生命周期。
- 目的地校验 BLUI 自有顶层 GHOST 窗体；来源校验 HWND/PID/线程/进程创建时间/窗口类，
  登记和合成前复查。最小化、受保护、隐藏、身份改变和不可用来源明确回退占位。
- 新独立纯几何模块提供最多四张预览及等比适配；清理接口关闭 DWM 登记，要求在关窗、
  加载、撤销和卸载前调用，附进程退出清理。纯 mock 回归与真实 GUI 集成验证分离，
  不读取/修改其他用户运行实例；详见 blui/TASKBAR_PREVIEWS.md。
- 19 项 DWM 纯 mock 回归通过，覆盖 HWND/PID 复用、目的地身份变化、最小化/保护占位、
  合成 API 失败与资源释放；活跃控制器保留到关闭/退出，避免丢失调用者引用后登记泄漏。

## 最新交付：任务栏大图标（2026-10-13）

- 基线 c8b8095，新增可选原生 operator 大图标绘制：32逻辑像素高分辨率图标、40逻辑像素
  点击区域；开始、应用和备用图标同样放大。默认普通 Blender 操作按钮不变，保留原生
  tooltip、禁用淡化及分组逻辑；任务栏专用垂直居中修正避免大图标裁切。
- 栏高56逻辑像素，结合显示器DPI和BLUI自定义界面缩放；菜单锚点共用几何，图标容量
  按实际宽度计算。新taskbar_metrics模块独立管理尺寸，未把额外逻辑堆入绘制文件。
- 修正INFO继承的View2D处理器抢占中键；应用按钮通过实时原生UI命中，空白处中键不
  启动旧应用或平移任务栏。Shift单击在按下时捕捉，非应用按钮Shift单击保留普通行为。
  命中读取当前处理事件而非未来坐标；快速点击后立即移开鼠标仍命中原来的应用。
- Release和219项完整纯回归通过（初轮与大批编译并发出现两项进程超时，编译后重测通过）。
  原生1/1.5/2倍实际绘制及左键/中键/Shift/空白处中键、最小化/恢复、ESC均通过；栏高
  56/84/112px，彩色应用图标包围盒30×27/44×38/60×53，无上下裁切。测试未启动外部应用、
  未实际隐藏系统栏；Windows前台权限拒绝仍明确报告，不弱化生产校验。
- 新便携包任务栏、开始菜单及快速点击竞态实测通过，目录为
  D:/BlenderUI/dist/BLUI-1.0.0-windows-x64-20261013-large-icons；旧包和用户运行实例未动。
  最终BLUI.exe SHA256=1082ECEC01904B042C0B81306287AAAF1353BC4611AF73410F38A329C0C7B25D。
  同名ZIP包含3812文件、125571207字节，全部CRC通过；无PDB/pyc/__pycache__，必需运行库、
  图标辅助程序、任务栏模块及说明齐全。提交目标仍为用户gh/blui，不推上游origin；
  导航检查两个用户未跟踪文件不纳入提交。

## 最新交付：独立任务栏、开始菜单与原生异步缩略图（2026-10-13）

- 基线 cf4c706，仍只向用户 gh/blui 提交。主代理统一构建及 GUI 回归，子代理分模块实现。
- runtime/client/worker 新增 previews、task_launch 与 start_* 白名单接口；原生 shell role
  窗体在没有节点画布时仍保持任务、显示器、图标及恢复守护心跳，缩略图失败降温。
- 开始菜单与多窗选择是独立原生窗体，不能把长菜单裁切在任务栏的薄 client 区域内。
- 本轮Release/实际UI/便携包/ZIP校验已完成。下列保留集成与修复记录；最终结果见本节末尾。
- 新增 folder_panel_model/folder_panels：文件夹映射到原生 Frame，扫描仍用隔离 scan Job，
  延后到没有模态交互才通过可撤销操作应用。刷新保留手工卡片和已有位置，只清理该面板
  自动生成的过期引用；目录、颜色、来源标记随既有原子布局保存，不操作真实文件。
- 开始菜单请求在创建 helper 前检查程序身份/固定项 schema 与枚举动作；结果消费不依赖
  菜单窗是否仍开着，关闭菜单后启动结果与固定项保存仍能完成。增加面板同步/schema纯回归。
- 已为新开始菜单、文件夹面板补充简繁中文词条；任务再启动错误进入任务栏状态而非静默。
  当前桌面纯服务122项与面板纯回归6项通过，native编译与实际UI仍待验证。
- runtime新增任务栏 pending 服务唤醒入口，修正 Files-only 下初始显示器快照为空而无法开栏的
  循环等待；增加独立配置/自有文件夹的原生映射面板回归，不操作用户文件或已有进程。
- 原生普通组件开窗排除 shell role 复制源；只剩任务栏时走正常默认尺寸的 fresh 分支，
  防止从开始菜单或托盘打开 Files 被复制成48px薄窗。首次编译发现新DNA字段对齐问题，
  子代理补齐明确padding后再统一编译，未运行或替换用户软件。
- 编译继续发现预览入口 UTF16转换函数名拼写不匹配本仓库头文件，主代理按utfconv.h修正；
  已完成其余897个编译步骤，重新增量链接并随后做实际缩略图夹具。
- 旁路审查补强：显示器定位失败不能让Blender timer停掉全部桌面服务，原生shell更新有
  操作异常边界与3秒退避；截断目录快照不能证明未返回引用已删除，保留这些卡片。
- 原生Frame复制会复用自定义ID，已在请求/持久化前修复唯一身份，并只将真正受其管理的
  直接子卡片来源标记随父Frame一起更新，手工卡片不被错误认领。
- 图标独立helper也补充2.5秒自身看门狗，避免撤销/加载取消Python父worker时留下卡在Shell的
  孙进程。新任务栏词条补简繁中文；DESKTOP/START_MENU说明真实功能、参考来源与边界。
- Release链接完成；缩略图原生13项（含无窗口、离线仅读缓存）通过，任务分组/再启动18项、
  shell角色生命周期14项、开始菜单隔离IPC671应用身份只读核验通过，仍待完整UI回归。
- 原生文件夹面板初次GUI回归通过；补充“复制Frame后首次刷新目标/来源标记”实测，以及按
  全部关联桌面和共享组计算新增卡片预算，防止扫描把整板推到不可持久化的1000项上限外。
- 开始菜单真实GUI发现内部C Operator不一定出现在bpy.types，误走旧版props fallback；
  子代理改用get_rna_type验证真实注册状态后继续回归，不以mock通过代替实际可用。
- 文件夹面板原生fixture补950个组内节点后再映射200项的预算场景，新增项必须在整图上限内，
  且最终snapshot仍可被严格模型验证；开始菜单能力检测增加2项回归共27项通过。
- 真开始菜单GUI通过独立screen/正常高度、内存搜索、固定项原子落盘、复用/开始切换和
  实际Escape。原文件工作区保持原样，全程无真实应用启动、电源动作或系统任务栏隐藏。
- 文件加载的窗口匹配同样排除旧shell HWND复制源；only-taskbar保存时新的窗口链为空，
  不再把NULL传到substitute_old；只有真实旧普通窗才能复用句柄，shell样式不会污染普通窗。
- 独立栏GUI通过Files-only pending、私有INFO/noCaption/noActivate、单图标分组/真实图标、
  多窗选择、Win10/11切换、自身最小化恢复、Escape及only-bar组件正常尺寸。
- 补守护确认隐藏系统栏后的原生栏贴物理屏幕底边：仅定位带合法TASKBAR role/身份的自有
  HWND，不改系统workarea/AppBar/注册表；恢复时退回work底边，新增纯几何回归。
- 新增check_shell_persistence保存/回读夹具，所有对象跨load重新查找；三角色重复保存、
  普通INFO保留、orphan清理及only-taskbar保存加载/普通窗样式待验证。隐藏状态GUI仅mock
  守护状态并定位QA自有任务栏，绝不真正隐藏用户系统栏。
- 保存回读fixture在open_mainfile时不跨Main替换保留temp_override的旧Window/Area恢复栈，
  跟正常加载一样从当前进程上下文进入，加载后才fresh lookup。
- 全部纯服务203项通过，helper三角色3轮保存/加载及only-taskbar保存/加载实际通过。
  单窗切换读取点击瞬间真实foreground（仍双重窗口身份校验），不依赖几秒前的active缓存；
  新增点击状态回归与任务栏/开始菜单截图采样，验证真的绘制而非仅RNA尺寸正确。
- 用户追加Shift+P：选中项通过原生node.join形成新Frame，位置不变、支持UNDO/组内操作，
  空选择不创建空框；菜单入口、本地化与使用说明同步。本轮仍继续原任务打包验证。
- 自动化进程可能被Windows前台权限拒绝，任务栏fixture只mock自身目标的foreground读取
  来覆盖切换分支；实际最小化/恢复仍操作经核验的自有HWND，拒绝激活必须明确报告。
- 真截图发现PreviewImage只有大预览slot，operator/menu的小icon slot为空，导致已加载icon_id
  仍绘制空应用按钮；现在同时提供两slot并把双份像素计入既有预算，含方向/尺寸去重回归。
- “新窗口”组件菜单增加独立任务栏入口，Files-only用户不必先打开画布/F3；应用图标修复后
  真任务栏截图采样54色，开始菜单135色，均已查看。文件夹复制首次刷新、整图预算GUI通过。
- Shift+P三预设原生按键/无空选框/世界坐标/JSON/UNDO/组内框实际通过；最终全部纯测试
  207项，原生缩略图13项、独立任务栏/开始菜单、保存回读与托盘6轮回归通过。
- 新便携目录20261013-shell已stage，README/DESKTOP/START_MENU与必需fileicon helper齐全；
  原版本与用户运行的4个BLUI进程保持原样。接下来验证便携包自身GUI与ZIP完整性后推送。
- 最后截图尺寸核验发现GHOST初始化setState会给开始/选择菜单重新添加CAPTION；这条常规
  状态初始化现仅作用NORMAL，全部shell窗保留构造时的无标题样式，补真实菜单样式断言。
- 菜单实际已600x680、136种绘制颜色；异步QA等待期间Windows可能让菜单失焦正常关闭，
  toggle测试先显式建立“菜单已打开”前置状态再点击，防把正确打开误判为收起失败。
- 便携QA raw exit复现两个旧shell_worker留存锁住python.exe；新增独立worker_lifetime模块：
  disposable shell/desktop助手仅以SYNCHRONIZE权限持有原父进程HANDLE，父退出时仅退出自己，
  句柄身份不随PID复用改变。原任务栏恢复守护不接此机制，继续可存活恢复系统栏。
- 两个明确为本轮便携QA遗留、父PID已退出的只读菜单助手已结束，不终止任何用户BLUI；
  新增真实自建父进程raw-exit夹具，验证disposable子进程自行退出而非外部清理模拟。
- 最终全部纯测试210项通过；原生SHIFT+P三预设、独立任务栏/开始菜单、映射面板、
  保存回读/only-bar正常窗、托盘6轮回归和真实parent退出生命周期通过。
- 便携包实际开始菜单600x680无CAPTION/绘制136色通过；缩略图13项再次在便携EXE通过。
  不接管通知区、系统托盘、Win键、Jump List和完整UWP索引，不声明已完整替换Windows Shell。
- 发行目录 `D:/BlenderUI/dist/BLUI-1.0.0-windows-x64-20261013-shell/` 及同名ZIP；ZIP
  3811文件、125525155字节，CRC全部通过，无PDB/pyc/__pycache__，含必需helper与三份说明。
  EXE与最终构建SHA256一致：`785D1E4568EFD27A8F8A2369BA5EEE2F898D9D9B80EB605991FC87F38CE6CC84`。
- Git只推用户gh/blui，普通提交，不触碰origin；既有用户版本与运行进程均保留。
  未跟踪check_navigation.py/.cmd不提交；本轮源码/说明/测试一并正常提交。

## 开发中：原生开始菜单（2026-10-13）

- 参考 Open-Shell 官方程序目录、固定/最近与异步搜索机制；未复制代码、安装或注入
  Open-Shell，不替换 Explorer。新增独立纯模型/worker backend；仅索引用户和公共
  KnownFolder Programs 的 `.lnk/.exe`，保留重定向、不解析快捷方式、不跟随子目录
  junction；有目录深度、条目、时间和响应上限。
- 搜索仅内存匹配应用名称/分类，不能执行搜索字符串；显式启动重新验证根路径、
  文件身份并在写入/删除保护下复查；固定/最近条目原子保存、备份、版本冲突保护。
- 系统入口为固定 allowlist；锁屏/重启/关机仅用户确认后调用原生 Windows API，
  不强制终止未保存应用。原生 INFO/窗口 Panel 分离为独立 `STARTMENU` 角色窗，
  避免窄任务栏客户区裁剪；入口不依赖桌面/节点区域，固定、分页和选择后关窗皆仅
  操作自有开始菜单角色。新增 UI/异步 facade，root 注册/worker 接入已完成，实际
  原生开始菜单窗体 UI 回归由主代理串行执行。
- 对外 worker API 固定为 `start_index/start_state/start_launch/start_system`，响应验证
  `start_menu_model.validate_index`；root 已接入注册、worker 和异步 facade tick。
- 新增 `test_start_menu.py`：严格模式、Unicode/命令文本搜索、Programs 范围/重定向、
  扫描预算、reparse拒绝、两次启动身份验证、原子备份/版本冲突和异步状态竞争，
  所有启动/电源动作仅 mock，不打开用户程序、不改变真实电源状态。
- 纯身份回归发现 Windows `DirEntry.stat().st_ino` 固定为 0，和启动复核的 `os.stat`
  文件索引不一致；扫描只对合格 `.lnk/.exe` 再用 `os.stat` 捕获真实身份，避免所有
  应用被误判“索引后变化”。框架允许包含空格的真实文件名，不将其当成命令执行。
- 23 项开始菜单纯回归全通过。补任务栏 Start 再次点击关闭、ESC 仅关闭自有
  STARTMENU/TASK_CHOOSER 的 operator；曾获得前台后失焦关闭 Start，自有文本/菜单/
  确认对话框模态期间保留窗口，前台验证失败不假定可关窗、不保存过期 RNA 对象。
- 真实机器只读扫描得到 671 个 Programs 应用，671 项路径/文件身份复核全通过，
  约 1.7 秒，无启动/电源操作。新增 `START_MENU.md` 明确 Programs/UWP 边界与官方
  设计参考、`check_start_menu_services.py` 只读辅助 IPC 验收和真实 owned-fixture 文件
  写入保护回归；开始菜单不共享/改写系统固定项或使用历史。
- 真实 fixture guard 验证进一步发现 READ_ATTRIBUTES 不参与 Windows 共享冲突；
  改成 GENERIC_READ + FILE_SHARE_READ 才真正允许读、拒绝同时写入/删除，避免名义保护。
- 24 项纯回归及真正隔离 worker 671 项只读索引/身份验证通过。新增主代理可串行运行
  的 `check_start_menu_ui.py`，覆盖独立角色屏/窗口尺寸、只读搜索、owned CONFIG 固定
  保存、正常窗口复用、任务栏再次点击收起及真实 Escape；不启动应用/执行电源操作。
- 补异步 refresh 先读取旧设置、save ACK 先完成再返回 index 的竞态：index 回复的
  revision 低于当前偏好时不回退固定列表。增加对应回归（总计 25 项）。
- 初次没有固定项时展示“全部应用”，已有内存固定项则打开固定页；明确进入空固定页
  不再误显示“全部应用”，避免筛选标签和实际结果不一致。Windows 设置/电源设置 URI
  已按微软官方当前文档核实，文档补充出处。
- 原生 UI 回归发现 INTERNAL C operator 不一定出现在 `bpy.types`，原检测误走同窗
  props fallback；改用 operator `get_rna_type()` 查询真实注册，补该场景及缺失时回退
  的纯回归，主代理再次安装脚本后重跑原生界面。

## 最新交付：框选与开窗修复（2026-10-13）

- 基线 `998058fbf7673c383fa2a647f3dabff5b2e880aa`；分支 `blui`，正常提交并推送到
  用户 remote `gh`，不推送上游 `origin`。本轮编译与发行校验已完成。
- 框选进入后无法释放：节点编辑器恢复时遗漏 Gesture Box 模态关联，导致鼠标释放、
  Escape/右键无法结束。补回 Box/Circle/Lasso/Viewer Border 的已注册模态关联，
  不改选择算法。三预设实际空白拖框/B键/释放/取消/减选、圈选取消及映射检查通过。
- 托盘回调时 CTX 窗口为空不代表 WM 窗口列表为空。之前误走 fresh 分支，令两窗
  复用同一 bScreen/区域绘制状态，第二窗保持灰底。现在从 live 列表找真实复制源；
  仅真正无窗口时复用原布局，新 OS 窗口都有独立屏幕。
- 新窗口区域的绘制缓冲被清空但继承源 redraw=0，顶栏可能留灰。首帧标记所有区域
  重绘并刷新；源布局恰好是所请求组件的默认布局才跳过冗余复制。桌面派生布局中
  请求 Files 仍打开原文件组件，不错误复制桌面。
- 新复制文件管理器第一次 init 前可能收到其他窗口的 NA_JOB_FINISHED。此时 runtime
  为 NULL且没有注册 reload callback，安全跳过该回调，后续正常 init/refresh；不吞崩溃。
- 旧包已真实复现第二窗仅1种清屏颜色及屏指针共享。最终构建/便携包均通过6轮托盘
  关闭/重开/重复开窗、屏身份与像素检查；便携包普通用户配置下两窗采样27/26种界面色。
  组件窗口、无窗口重开、跨窗文件拖拽和拆窗压力回归再次通过。
- 新包：`D:/BlenderUI/dist/BLUI-1.0.0-windows-x64-20261013-interaction-fix/` 及同名 ZIP。
  ZIP 125561502 字节、3797 文件，CRC完整性通过，不含 PDB/pyc/__pycache__。
  EXE与最终构建 SHA256相同：`A58571C83BA5AE49A133211202F5FF2876F6C2EE9370DD0C679D5FCE02B158B3`。
- 新增 `check_desktop_selection.py` 和 `check_tray_windows.py`，只操作自己的 QA PID。
  使用说明补充框选释放/取消；归档 helper 再次过滤 QA 引导产生的 stdlib 缓存，不删除
  QA 文件。旧发布、用户运行进程、未跟踪 `check_navigation.py/.cmd` 保持原样。
- 旁路审查发现多屏首次恢复只认领首个空板、同屏历史树可能影响窗口复用的待验证问题；
  用户已明确本次是软件启动/托盘入口，本轮未扩大到多屏恢复改造，留后续单独回归。

## 前次交付状态（2026-10-13 桌面版）

- 本轮基线 `95b1124ff32c9891c514f0e406d4c7cf46fd0c23`，分支 `blui`；仅推送用户
  GitHub remote `gh`，不推送上游 `origin`。发行版已组装、校验；本次提交随后正常推送。
- 桌面是可选的原生节点组件，默认六组件启动布局不变。文件图标透明显示，
  支持原生多选、Frame 面板、真正的 Group、时钟、计算器及显式启用联网的天气。
- 多显示器各自保留布局；跨桌面拖动移动引用，Ctrl 拖动复制引用；拖到文件夹走
  真实 FIFO 文件任务，冲突不覆盖。布局约每 30 秒异步原子保存，含有效备份。
- 布局超预算或序列化失败仅报告持久化错误，不停止桌面服务 timer；多板记录回滚，
  保留现场排版并在修正后继续自动保存，新增纯回归覆盖失败及恢复。
- PNG/JPEG 背景支持 alpha、适应/填充/拉伸/居中/平铺/跨显示器、对齐及透明度；
  各屏独立设置。隔离进程解码，主界面仅绘制有预算的缓存 GPU 纹理。
- Windows 任务栏默认保持原样。显式隐藏前记录原可见状态，两独立恢复守护覆盖
  父进程退出、助手失败和 UI 心跳超时；窗口身份复核防止 HWND 复用误操作。
- 快捷方式优先取原始 ICO/PE 真实高分辨率资源；便携包必须携带静态 CRT 的
  `BLUI-fileicon.exe`。托盘明暗/高对比度及启动首帧底色跟随只读 Windows 设置。
- 修复 4.5 式停靠的区域释放后访问、延迟关窗及悬空上下文，离窗光标保持原生。
  视频编辑器保存自己的起止范围，播放 timer 仅持有范围快照，不持有 SpaceSeq 指针。
- Release 编译通过；桌面纯服务 107 项、任务栏 19 项、原生主题 26 项、图标资源
  9 种夹具通过。真实画布/组/背景 GPU/模态稳定性/双桌面保存恢复/多选跨窗拖动、
  文件夹移入及冲突拒绝、双视频范围及基线旧 SDNA 回归通过。
- 本轮再次通过三套键位、停靠/修饰键/控制台迁移/跨窗鼠标停靠、绘制 UV 像素、
  图标大小、文件夹系统菜单原位更新和区域/四角拆窗压力回归。
- 文档关闭/取消、组件窗口及多窗口隔离通过；无窗口托盘夹具旧发行版也被文档确认
  拦住第二次关闭，夹具仅对自己窗口显式 force_close，文档保护仍由独立回归覆盖。
- 已生成：`D:/BlenderUI/dist/BLUI-1.0.0-windows-x64-20261013-desktop/` 及同名 ZIP。
  ZIP 125500562 字节、3797 文件，CRC 完整性通过，不含 PDB/pyc/__pycache__。
  便携版真实画布综合回归、六组件启动及 256px 独立图标助手通过；EXE/助手/最终
  session.py 与构建 SHA256 一致。完成本次推送即暂停继续开发。
  不覆盖旧发布、不关闭用户运行中的旧版本；保留未跟踪 `check_navigation.py/.cmd`。
- 边界：不是完整 Windows Shell/通知区/AppBar，不管理 Windows 虚拟桌面；PNG 透明
  露出的是 BLUI 画布而非 OS 窗口穿透。视频播放头和条带仍共享。崩溃可能丢最近一次
  保存后的修改，撤销排版不能撤销磁盘文件操作。物理多屏热插拔需更多硬件验证；
  自动测试没有隐藏真实用户任务栏。使用方法及天气许可见 `blui/DESKTOP.md`。

## 开发记录（2026-10-13，以下按实现过程保留）

- 用户明确“多桌面”指多显示器。各屏布局独立保存，断开显示器不丢布局，重连恢复；
  不管理 Windows 虚拟桌面。新增天气/时钟/计算器卡片、局部视频时间线范围任务。
- 桌面文件改为真实原生节点的透明图标单元，原生 Frame 做图标面板，真实 Group 容纳
  文件引用；图标在独立 BLUI-fileicon 子进程读取原始 ICO/PE，失败使用原生类型图标。
- 用户授权系统任务栏隐藏/恢复，将通过显式开关和独立崩溃恢复守护实现，默认不隐藏。
  参考 RetroBar 机制，具体接入和测试仍在进行。
- 新增安全 AST 计算器、秒级时钟、用户启用才联网的天气（Open-Meteo/CMA 模型），
  15 分钟原子缓存与断网旧数据显示；天气及小工具 16 项服务测试通过。
- 多屏 all-board 原子快照、单调 revision、防陈旧跨屏转移、30 秒自动保存和显示器
  拔插布局保留服务已实现，18+16 服务测试通过；客户端全部 FS/进程 IO 移出 UI timer。
- 背景图新增 PNG/JPEG 隔离解码、原生 PRE_VIEW cached GPU 绘制、六种布局/对齐/透明度，
  15 项服务/真实 alpha 解码测试通过；背景透明是露出 BLUI 画布，不改变 OS 窗口透明。
- 本批正在接入原生菜单/系统 CF_HDROP 复制剪切粘贴、FIFO 重命名与隔离回收站，
  原生透明图标拖动支持跨屏迁移引用及拖入文件夹；真实界面验证待统一编译。
- 桌面原生图组支持 Ctrl+G / Tab / Ctrl+Tab / Alt+G 和 Frame 父子关系，JSON 保持共享
  Group 引用；图结构 6 项独立测试通过。背景图服务 15 项通过，分屏/跨屏采用物理屏坐标。
- 视频编辑器新增每个 SpaceSeq 保存/复制的本地起止范围，旧文件首次从 Scene 复制后
  独立编辑；绘制/Frame All/预览范围/播放循环使用发起编辑器范围。播放 timer 只保存
  起止整数，源关闭或焦点改变不保留悬空 SpaceSeq 指针。Scene 播放头/片段仍共享。
- RetroBar/ManagedShell 仅参考机制，不移植 WPF 或复制源码。新增显式任务栏隐藏/恢复、
  原可见状态 journal、父死亡/15 秒无心跳恢复及第二守护；WinEvent 事件驱动任务刷新。
  自有 HWND 多重身份核验和断屏回迁模块已接入；不改变系统 AppBar/自动隐藏/工作区设置。
- 集成审查修正同 ID 恢复覆盖用户编辑、背景选图/关闭后的陈旧回包、Frame 相对坐标
  跨屏偏移、组内根背景等待及目标分配中途失败遗留；新增 v2/adapter 19 项测试通过。
- 图标预览按真实像素哈希共享缓存，并限制总像素预算；Desktop 使用 Known Folder
  DONT_VERIFY 路径，支持 OneDrive 桌面重定向，不在 UI 枚举目录或解析链接。
- 当前统一编译：首轮修正 RNA filepath 参数和 GHOST include 路径，视频旧 SDNA
  member-exists include 缺失正在修正；尚未把开发版本标为可交付。
- 视频旧 SDNA 检查改用本 fork 的 DNA_struct_elem_find 并补空 timer/customdata 防护。
  自动恢复请求 admission/Undo 取消后可重试；图标面板高度/大宽度保存和隐藏子组
  选择状态隔离已修正，防止根菜单误剪切/回收未选择组内文件。
- 桌面全部当前纯服务测试 98 项通过（含新 v2/Frame 跨屏与分配失败夹具）；任务栏
  19 项独立测试通过，原生 GUI/发行版回归尚未运行。
- 完整原生 Release 构建已通过；修正包含路径/本 fork API 后，桌面服务测试更新为
  101 项通过。开始依次运行真实原生窗口/节点组/背景/多屏引用/视频范围与模态稳定性回归。
- 原生桌面移动/Undo/保存恢复/FIFO复制/native drop 与背景 GPU 回归已通过。
  真实组创建回归发现 generic group 路径调用空指针，正在修复；视频 RNA 更新发现
  无 owner ID 的 Space 指针仍查找 Screen，已给共有 helper 加 null/ID_SCR 防护。
  此开发构建不打包，待所有相关原生回归通过后交付。
- 节点组崩溃根因为 fork 删除的标准/Virtual socket draw/color 回调；节点编辑器已恢复，
  现恢复对应原生回调。桌面真组沿用 Tree 节点迁移但不生成工程 GroupIO/socket，先拒绝
  带工程 socket 的节点，保持文件/面板/小工具/共享子组语义。待重编译和真实组回归验证。
- 真组 Ctrl+G/Tab/Ctrl+Tab/Alt+G、Frame 父子、循环拒绝和共享子组 JSON 回归通过；
  综合回归在可恢复的快照比较处停止，正在检查 Group ID 名称唯一后缀，未发生新的崩溃。
- 桌面初始扫描/恢复取消默认全选高亮；图标助手改静态 CRT，独立便携运行不依赖开发机
  VC runtime。背景原生 PRE_VIEW 实测通过；图片 alpha/多屏跨屏布局截图已检查。
- 综合 JSON 恢复差异来自 Blender 全局唯一 Group ID 名称加后缀，新增独立持久显示名，
  不删除/重命名其它桌面仍引用的旧组。视频双编辑器局部范围、播放源改变、复制及真实
  .blui 保存重读回归通过；旧发行 startup 文件夹夹具未找到，另补 source 旧文件兼容验证。
- 从基线 commit 归档旧 startup，旧 SDNA 本地视频范围首次初始化/不跟随 Scene 回归通过。
  综合图组/面板/widget/跨窗口引用/异步双桌面首次备份恢复全部通过。
- 真实鼠标拖拽前置窗口定位发现 Win32 未实现 generic getOSWindow（返回 null），
  GHOST C bridge 改明确 getHWND；待重编译后重跑实际 mouse/native path drag。
- 原生多选 path drag/source token 已真实激活；跨窗夹具需将模拟事件投递给目标窗口，
  event_simulate 不走 GHOST 跨窗转发。NodeDrop桥同时转发真实 event 的 Ctrl 和 View2D
  位置，不再读取目标窗口可能陈旧的 eventstate，以保护复制/移动语义。
- 实际 native 多选跨窗 Ctrl-copy 已通过；默认移动拖动发现 PRESS 立即清掉其它选择，
  采用 Blender 原生 select_passthrough + CLICK 回落键位，保留拖动多选且点击仍可单选。
- 画布模态压力回归通过：真实 G 拖动、文本输入及缓存编辑器上的模态处理中，异步恢复
  等待释放；Escape 后安全更新，Undo 恢复内容并取消旧 epoch 的任务/结果。
- 新增 `blui/DESKTOP.md` 说明入口、多屏/文件动作、自动保存边界、天气授权/来源、
  任务栏恢复机制及视频共享播放头边界，UTF-8 无 BOM。

- 基线：`95b1124ff32c9891c514f0e406d4c7cf46fd0c23`，上轮已推送到 gh/blui。
- 用户要求继续：快捷方式清晰度、托盘明暗主题、启动瞬间底色、4.5 离窗光标、
  拖出崩溃修复，以及基于原生节点/文件管理器的桌面画布与任务栏基础。
- 真实 crash.txt 证实停靠关闭源区域后仍读失效的文件管理器上下文，优先修复
  生命周期和增加文件管理器多区域压力回归，而不是吞掉访问违规。
- 图标资源提取、原生 Windows 主题/首帧、窗口稳定性分模块并行处理；主代理接入画布。
- 用户已确认启动问题仅为启动瞬间底色，不改 BLUI 内容主题或用户系统设置。
- 桌面/任务栏作为可选独立 BLUI 组件；不注册为 Windows Shell，不隐藏系统任务栏。
- 图标直接读取 .lnk IconLocation 与 ICO/PE 最大真实资源（数据映射，不执行 DLL），
  避免缓存放大小图；托盘图标修正错误资源 ID，菜单主题与首帧分别按 Windows 设置适配。
- 恢复已有原生节点编辑器注册及节点移动宏，增加原生 FOOTER 作为任务栏承载，
  画布模型/持久化、异步文件枚举、任务枚举和界面分模块实现。
- 停靠关闭后先清空上下文；预览双侧及源 SpaceLink 身份验证、全屏/临时目标拒绝、
  延迟关窗身份保护和 child windows 重挂已接入；离窗光标使用 4.5 的 PICK_AREA。
- 画布目录枚举、布局持久化及外部任务枚举在有超时的独立助手执行，UI 不访问慢目录。
- 托盘 owner-draw 明暗/高对比度/强调色、正确 APPICON 与 Explorer 重启恢复已实现；
  首帧只读 AppsUseLightTheme 清屏；新增原生像素/GDI/托盘恢复回归待统一构建。
- 文件管理器迁移清理旧窗口滚动 timer/重命名状态；partial-edge JOIN 不再使用
  可能被 trim 释放的源区域，新增 48 次区域变更、错位合并、8 次四角拆窗压力回归。
- 原生节点文件/便签卡片、平移缩放/多选拖动、目录快照、保存恢复、文件拖入、
  复用 FIFO 复制/移动与原生 footer 任务栏接入；移除卡片保留真实文件。
- 任务按钮按 HWND/PID/线程/进程创建时间/窗口类多重核验，避免句柄复用误操作。
- 桌面服务 15 项无 GUI 回归通过：扫描上限、路径去重、JSON/备份恢复、并发保存、
  助手崩溃/超时/消息读锁、任务身份过期拒绝；新增界面简繁本地化。
- 首轮编译发现托盘备用图标宏 ANSI/Unicode 类型不符，正在修正；用户真实崩溃日志
  已备份，再以旧发行版在独立夹具上验证崩溃基线，不结束用户原有窗口。
- 旧发行版压力夹具确认访问违规（退出 11），修复构建待回归；原生托盘主题测试
  26 项通过，图标真实分辨率/透明边/方向逐像素测试通过。
- 审计发现异步恢复节点可能撞上原生拖动/文本按钮持有指针；新增窗口模态活动只读
  API，所有结果等待交互结束后走原生 Undo 操作符应用，Undo/读取文件取消过期任务。
- 画布任务增加 UUID/session epoch 校验、persistent Undo/load 失效钩子与全窗口模态 gate；
  结果应用逐项错误保护，默认保存布局可在新会话恢复，文件选择期间变化时复核源画布。
- 独立图标 9 种夹具（含 PE 负资源ID、DLL不执行、透明裁边）和桌面服务 16 项全部通过。
- 画布保留默认六组件启动布局，作为可选 NODE_EDITOR 组件打开；目录改变使旧枚举
  失效，默认布局保存到配置目录而不写桌面实际文件，待真实窗口操作/Undo/持久化回归。
- Release 构建通过，修复版压力测试 48 次区域变更、4 次错位合并、8 次四角拆窗及
  过期关闭/目标/拖动取消全部通过；旧发行版相同夹具访问违规。
- 画布拖放注册早于 Python 启动，增加轻量原生代理延迟解析 Python 导入操作符，
  避免启动时未知 dropbox；原生节点宏和画布 UI 启动检查通过。
- 增加真实画布窗口回归：文件卡异步加载、原生移动/Undo、卡片删除不删文件、
  保存恢复、FIFO 复制、原生 dropbox 代理及仅 QA 自身窗口的任务栏激活。
- 原生代理修正 C++ RNA flags 枚举显式转换；补充画布 transform/文字编辑 modal、
  隐藏缓存编辑器、Undo/session epoch 的防崩回归，待窗口测试统一执行。
- 异步应用明确传 Python operator undo=True，避免计时器默认不记入撤销栈；
  创建画布有原生 Undo 标记，尊重用户全局撤销选项，关闭时提供显式启用入口。
- 已查明工厂 startup 隐藏 Cube 遗留 EDIT 模式使原生 memfile Undo 第二步被禁用。
  工厂生成改为中性 OBJECT 模式，不改变用户已加载工程、不绕过原生模式安全限制；
  回归夹具使用中性模式并检验撤销，N 侧栏原生快捷键接入。
- 画布窗口功能回归通过（含移动/Undo、持久化、复制、原生 dropbox 与任务身份）；
  恢复节点选择工具注册，避免 footer 报默认选择工具不存在。
- 工厂生成器按已有组件名称匹配并先临时改名，保证重复生成不会出现 Files.001；
  生成成功直接结束 QA 进程，不写共享 quit.blend 恢复文件。
- 画布稳定性回归通过：原生 transform、便签输入、缓存编辑器切换期间阻断替换，
  ESC 后安全应用、Undo 恢复且取消旧助手；选择工具自带最小框选映射避免缺失键位。
- 编辑器类型菜单只提供桌面画布子类型，不重新暴露无关的着色/几何/合成工作区。

## 当前状态（2026-10-12）

本轮接续文件夹菜单慢/加载失败、绘制模式 UV 线框、部分快捷方式图标过小反馈，
并回移 Blender 4.5 式区域分割、合并、停靠和跨窗口迁移交互。
分支：`blui`；用户 GitHub remote：`gh`（LHT02/BlenderUI）。
本轮基线：`9a46a8948106e2c38d9446bc85f8836aed236fb9`。
上游 Blender remote `origin` 不用于推送。

## 文件管理器

- 一级菜单保留常用操作及 Blender 原有导航、刷新、外部操作、编号、新建文件夹、
  书签、显示/大小/级联/排序；重复项合并，顶部不再重复原生工具栏的操作。
- Windows 系统菜单折叠到“更多”，扩展枚举/执行和属性窗口在独立 Python STA
  助手运行，不在 BLUI UI 线程加载扩展 DLL。子菜单按需加载。
- 普通文件夹的 Folder/AllFilesystemObjects 与 Directory 关联分别在两个独立助手
  枚举，渐进合并，保留真实父 IShellFolder 和子 PIDL，不使用错误的桌面目标替代。
  诊断复现两组在同一 COM 进程汇总时阻塞，而单组正常；未修改注册表或禁用扩展。
- 选择稳定 200 ms 后预加载；健康助手复用。返回结果原位更新仍打开的主/子菜单，
  不必重新右键。一个分组超时/失败不隐藏另一个分组的可用操作。
- 分组菜单使用独立的外部命令 ID 路由，token 更新使旧菜单失效，避免跨助手命令
  编号冲突和复用后执行错误目标。原生弹窗仍打开时保留对应隔离会话。
- 目录类型取缓存 RNA 标志，不在 UI 线程 stat 网络路径；目录快捷方式仍按 .lnk
  自身加载系统菜单，盘符保持普通原生路径。
- Windows 对消息文件的短暂读/删除锁在下一 UI tick 重试，不阻塞或中断菜单加载。
- 新增界面、状态、提示跟随 Blender 翻译设置，提供简体/繁体中文；
  Windows 原生文字保持系统提供的语言。
- 保留内部原生文件拖动预览、目标高亮、Ctrl 复制/Shift 移动及离窗 OLE 移交。
  文件任务使用独立 FIFO 助手，拒绝同名覆盖及自身子树目标。

## 快捷方式与图像

- 图标提取拆成 GHOST_FileIconWin32.cc，按实际可见图标细节选择系统图标档位，
  修正只有 16/32px 内容却放在 256px 透明画布导致缩略图过小的问题。
- 仅对过度填充的 jumbo 回退画布裁边，保留真实高分辨率图标留白，
  支持旧 AND mask 透明度；原有上下翻转修复和一次方向转换边界保留。
- 图像编辑器每次仅加载一个独立临时文件，不共享同路径缓存、不自动展开
  图像序列/UDIM/多视图。替换/关闭后释放无其他编辑器引用的临时图像。
- 移除可选 UV 编辑器/模式，旧 UV 布局归一为图像视图；保留内部依赖库。
- 图像查看/绘制不再绘制场景网格 UV shadow，即使旧 show_texpaint 设置开启；
  移除不适用的 UV 绘制菜单/面板，保留绘制、遮罩等适用覆盖层。

## Blender 4.5 式窗口交互

- 正常四角手势统一进入一个模态状态机：区域内分割、相邻边界合并、
  非相邻区域四边停靠、中心替换、跨 OS 窗口停靠、窗口外拆为新窗口。
- 释放鼠标前只显示预览，不提前修改布局；Escape/右键取消。
  支持 Ctrl 比例/邻近顶点吸附、Alt 精细比例；手势开始时按 Ctrl 仍为区域交换，
  开始时按 Shift 仍为复制独立窗口。默认/旧版/Industry Compatible 键位配置通过。
- 圆角分割/停靠目标框、源区域暗化及编辑器类型提示；首次进入/退出明确标记重绘，
  鼠标停住也显示目标，完成/取消后清除预览。
- Windows 命中按真实 OS Z-order 和客户区判断，避免多个重叠窗口被错误识别为
  第一个窗口；跨窗口坐标使用已有 DPI 转换接口。
- 移动、拖出、Ctrl 交换迁移真实 SpaceLink/区域数据，保留控制台解释器、变量、
  历史和未保存缓冲区，不用克隆代替移动；Shift 复制保留独立复制语义。
- 中心替换和合并经过目标文档保存/放弃/取消确认；异步确认后核验活跃窗口、
  区域及源编辑器身份。源在提示期间改变时安全取消，不覆盖目标。
- 单区域源窗口在模态处理器结束后延迟关闭；多区域源关闭原区域；
  无法关闭时保留内容并提示，不强行破坏布局。
- 这是向现有 BLUI 分支回移 4.5 布局交互，不是整套 Blender 内核升级。
  参考上游 `v4.5.0/source/blender/editors/screen/screen_ops.cc` 和 `screen_draw.cc`。

## 文档保护

- 关闭图像/文本窗口、关闭区域、删除工作区或替换图像时提供保存/放弃/取消。
- 保存失败/另存为取消保留文档。隐藏缓存文档保存时临时激活其工作区和编辑器，
  使用真实所属窗口上下文，完成后恢复原视图与编辑器类型。
- 多窗口工作区保存、最后工作区保护、加载失败保留当前图像等上一轮行为保留。

## 代码布局

- `scripts/modules/blui_explorer/`：隔离 Shell、分组目录菜单、消息、文件任务、本地化。
- `scripts/startup/bl_ui/space_filebrowser_shell.py`：预加载、动态子菜单及原位刷新。
- `scripts/startup/bl_operators/blui_documents.py`：文档确认、保存和延迟关窗。
- `source/blender/windowmanager/intern/wm_blui_documents.c`：原生文档确认桥接。
- `source/blender/editors/screen/screen_dock_*.c`：分别负责目标计算、预览、
  检查后的布局应用、模态交互；`screen_detach.c` 负责新窗口迁移。
- `intern/ghost/intern/GHOST_FileIconWin32.cc`：Windows 图标提取及尺寸修正。
- 新逻辑按职责拆分，未继续集中到一个上帝文件。

## 验证

- Release 构建和安装通过：`D:/BlenderUI/build/bin/BLUI.exe`。
- 13 项服务回归通过：文件/压缩安全、真实扩展子菜单、进程崩溃/超时/巨大请求、
  分组 ID 路由、部分失败、健康助手复用及 Windows 消息文件短暂占用。
- 四边停靠、中心保存/取消、隐藏缓存保存、源改变取消、相邻合并、
  四角拖出与 Escape、Ctrl 交换、Shift 复制、控制台状态迁移真实窗口回归通过。
- 真实跨 OS 窗口鼠标停靠通过，截图确认圆角停靠框和类型提示可见；
  夹具仅操作自身 QA PID 的窗口，用户运行中的两套旧版本未关闭。
- 选中两个文件夹的菜单原位渐进更新实测 1.266 秒；暖缓存复用通过。
- 绘制像素回归：旧版本 8530 个线框差异像素，修复后 0。
- 16px-only 图标回归：旧版本可见绿色像素 576，修复后 14229。
- 已打开主/子菜单异步刷新、简繁/关闭翻译、文件操作及三套键位配置通过。
- 原生内部鼠标拖入文件夹、目录快捷方式导航及真实 7-Zip 子菜单回归通过。
- 发行版启动、控制台停靠/拆窗回归通过；发行 EXE 与最终构建 SHA256 一致。
- ZIP 完整性及排除规则校验通过：3761 文件，不含 PDB、pyc 或 __pycache__。
- 未宣称整套历史测试全部重跑；Windows 跨应用 OLE 尚无完整端到端自动化覆盖。

## 打包与提交

- 新发行目录：`D:/BlenderUI/dist/BLUI-1.0.0-windows-x64-20261012-docking/`，
  按已有 `_package.py stage` 允许列表组装完整运行时，排除 PDB/字节码缓存。
- 已生成 ZIP：`D:/BlenderUI/dist/BLUI-1.0.0-windows-x64-20261012-docking.zip`，
  122032491 字节；构建、发行版启动及 ZIP 校验通过，准备 GitHub 提交推送。
- 完整解压目录运行 `BLUI.exe`，不能只复制 EXE；隔离菜单助手依赖内置 Python。
- 已交付的 `20261012-ui` 及 `20260917-explorer` 目录/ZIP 保持原样。
- 历史未跟踪 `blui/tools/check_navigation.py` 和 `.cmd` 原样保留，不纳入提交。
- 完成打包、校验及正常推送到 `gh/blui` 后，按用户要求暂停继续开发。

## 边界

- 第三方 Shell 扩展首次加载仍可能慢，但在隔离进程运行，已有分组结果保持可用。
- 本项目尚不声称完整替代 Windows Explorer。

## 独立任务栏子代理进展（2026-10-13）

- 原生新增明确的 TASKBAR / STARTMENU / TASK_CHOOSER 窗口角色和只读 RNA 标识。
  新窗使用自有临时 INFO layout，不复用桌面 footer，不新增默认工作区；Windows
  创建即为无标题栏 tool window，避免辅助栏/菜单混入应用任务列表。
- INFO 主区域按角色使用 Blender 原生 Header / Panel 绘制；菜单与多窗选择
  使用独立正常高度窗体，避免被 48px 任务栏客户区裁剪。待主代理编译/真实 QA。
- 新增纯应用分组/多屏几何模型；任务快照增加内核验证的 executable、app_id、
  group_key、monitor，保留原 PID/线程/创建时间/类名身份校验并过滤 DWM cloak。
  显式新实例只二次验证当前桌面程序的完整 exe 路径、不经命令壳；UWP/代理宿主
  与不可验证窗口不提供此动作。子代理不改共享 client/worker，主代理接入 task_launch。
- 独立 taskbar_windows 模块以新鲜 RNA 角色+自身 HWND 双重约束窗口生命周期；
  每连接显示器一栏，物理工作区/DPI定位；断屏只回收自身栏，自有菜单夹在对应
  显示器工作区。布局支持左侧/居中，菜单另开 STARTMENU/TASK_CHOOSER 原生窗。
- TASKBAR 单独 NOACTIVATE，STARTMENU/CHOOSER 保留键盘焦点；角色窗不写入
  启动文档窗口链，回读角色清正常；新增菜单 ESC 原生键位，正常组件窗复制
  仍由 calloc 建立 NORMAL 角色。辅助窗口恢复只在显示拓扑改变时检查。
- 新增独立任务栏原生 Header、应用多窗选择/设置 Panel、应用图标分组动作模块。
  画布 footer 已撤去重复任务按钮和时钟，只留文档/文件操作状态；菜单增加独立
  栏入口与 Folder Panel 入口。单窗点选激活/最小化，多窗独立选择，Shift/中键
  新实例和明确按钮复用隔离 task_launch；旧系统栏显式恢复入口持续保留。
- 首次统一构建 makesdna 指出 wmWindow 新角色导致 64bit 对齐不足，已添加明确
  4-byte padding 保持 8-byte 总增量；未运行子代理 GUI/Ninja，主代理继续编译。
- 原生应用分组顺序跨激活保持稳定；保留明确 APPWINDOW 的自有子窗任务，排除
  tool/cloaked 窗；Shift/中键 invoke 增加安全错误报告，不传播异常到交互事件循环。
- 新增纯测试夹具，覆盖应用唯一分组、UWP/未知宿主不误合并、原始快照不变、
  负坐标/DPI多屏菜单夹取、身份/路径变更与高权限只读拒绝、新实例无shell参数。
- 应用分组与安全启动纯测试 18/18 通过，日志 `D:/BlenderUI/build/taskbar-groups.log`。
  新增模拟 bpy role-window 夹具验证每屏唯一栏、pending服务、断屏/失败回收只作用
  自有辅助角色、正常窗不关闭，以及菜单定位无跨屏/稳态不重复系统定位调用。
- 首次 Files 入口监视器快照尚空时，菜单只记录不可变源/目标身份并非阻塞等待；
  正常高度原生窗先响应键盘焦点，后台快照回来兑现定位。关闭/注销清延迟记录。
- 辅助 INFO layout 采用明确持久化内部标记；WM_check 只清理已无任何窗口引用的
  标记 layout/screen，不处理普通原生临时编辑器。TASKBAR 的后续状态初始化也跳过
  激活；Files-only 首次开栏失败保留 pending 服务意图，退避后可重试不丢请求。
- 已提供主代理串行运行的 `check_taskbar_ui.py`（子代理未运行），覆盖真实自有
  窗口的 pending 开栏、无标题/不激活、INFO独立screen、exe图标缓存、单图标分组、
  多窗选择/ESC、布局切换、自身最小化恢复及只剩栏时新建 Files 正常尺寸。
- 各屏独立任务筛选时使用各屏独立图标顺序缓存，避免不同显示器绘制互相重排；
  居中布局两侧补偿固定托盘/时钟宽度，应用区围绕整窗中线而非剩余宽度居中。

## 2026-10-13 桌面文件缩略图（开发中）

- 新增 BLUI.exe 专用早期 `--blui-file-preview` 隔离入口，复用文件管理器 `IMB_thumb_manage` 的图像、视频、Blend/资源嵌入预览与字体缩略图逻辑；不启动窗口、Python 或用户启动文件。
- 子进程独立 3 秒看门狗、较低优先级、尝试 768 MiB 单进程内存上限；输出仅 256 像素上限的 RGBA。云端离线占位文件只读取已有缩略图缓存，不为预览触发下载。
- 新接口与快捷方式高质量图标助手分开，失败回退原图标。尚待缓存集成、构建和测试。
- 新增 `thumbnails.py` 与 `thumbnail_cache.py`：每批 2 项、3.5 秒父层超时、严格 256×256/像素长度校验；主线程只查询内存和创建预览 ID，60 秒异步复查文件变化，失败 120 秒降温、保留原图标。
- 桌面 FileCard 优先显示独立缩略图缓存，快捷方式、目录及不能预览的文件维持既有高质量图标。缓存上限 1000 路径/32 MiB 像素并去重；队列提供 retry/fail/cancel_pending，异常和 Undo 不会锁死加载项。
- 增加纯协议/缓存测试（方向、透明通道、尺寸与长度、超时/崩溃回退、候选字符串筛选、内存预算、降温重试、异步更新）；补原图标队列 admission 失败重排，防止请求繁忙时永远不再加载。
- 纯缩略图协议与缓存测试已通过 16 项；新增原生无 GUI 夹具，覆盖透明 PNG 方向、宽图缩放、MTime 更新、Blend 内嵌预览、真实字体/AVI、损坏与不存在文件回退，等待主构建后执行。夹具先检查新 binary 入口特征，防止对旧 EXE 传未知参数意外启动正常 UI。
- 预览早入口先检查云端离线属性；仅在线文件先初始化 FFmpeg 再调用原文件管理器扩展分类，以保留 `.ogg` 的视频/纯音频判定行为，避免分类探测提前读取云文件。未更改原文件管理器自身预览流程。
- 原生夹具补充私有文件 OFFLINE 属性模拟（只回已有缓存、不解码修改后的源）和自有 helper PID 全窗口只读枚举，检查后台预览不创建空白 BLUI 或隐藏托盘宿主窗。

## 2026-10-13 Shift+P 原生图标框回归夹具

- 新增 `blui/tools/check_canvas_frame_shortcut.py`，用真实窗口输入验证 Blender、Blender_27x、Industry_Compatible 三套键位预设的 Shift+P。覆盖选中 A/B 加原生 Frame、未选 C 留框外、可见世界坐标不变、无残留模态、空选不建框、JSON 保存/重建父子关系、原生 Undo 及真实节点组 edit_tree 内加框。
- 夹具只使用自有进程与临时文件；停用桌面持久化和异步定时器，不操作系统任务栏、真实桌面文件或用户配置。Undo 后按自有 HWND 和树名称重新取得 RNA，避免缓存已替换的 Main 指针。
- 仅完成脚本语法检查（通过）；子代理未运行 GUI、构建或提交，待主代理统一构建后串行实测。

## 2026-10-13 Open-Shell 双栏开始菜单修订

- 图标 job admission 仅消费内存队列并提交隔离提取，允许私有 shell 在无真实交互时继续加载图标，不被 NORMAL 的保守 hover 守门饿死；Node/Canvas RNA、背景与缩略图的原模态守门不放宽。图标结果创建预览的既有主线程机制保持不变。

- 六组原生栏高/图标/UI-scale 实测完整 PASS：32/16、80/64、160/64 × 1x/2x，PNG 实际 glyph 大小跟随设置、图标无裁剪、Start左侧与center应用命中独立；日志 `D:/BlenderUI/build/shell-redesign-appearance2-native.log`。64逻辑glyph实际约60×53，2x约119×107，已排除“只长按钮不长图标”。
- AppBar 文档明确当前边界：显式隐藏原系统栏只改可见性、不解除 Explorer 的注册预留区，可能保留下方空带；跨 BLUI 进程仍各自标准注册，未全局去重。不会暗改 SPI_WORKAREA 或外国 AppBar 注册。

- 通知区槽位保持24逻辑像素宽和正常通知glyph尺寸，点击高度跟随主任务按钮，确保大小变化时托盘图标也垂直居中，不留在高任务栏的上边缘。

- 原生尺寸 QA 揪出 icon_preview 大于32逻辑像素时横向仍被 Blender 普通图标按钮40px最小宽规则压扁，导致64设置只长高不放大glyph。限定显式 opt-in 的 UI_BTYPE_BUT+ICON_PREVIEW 保留缩放后方形宽度，普通原生按钮和其它preview类型不变；待重新编译六组像素实测。

- 通知 UI 原生复跑完整 PASS：8 个私有真实 NIM 图标及透明缓存/绘制、真实 native LEFT/RIGHT 事件与版本4 uid/坐标回调、独立 420×560 overflow UIList、DELETE/异步helper退出/源WNDPROC恢复；日志 `D:/BlenderUI/build/shell-redesign-notification-ui2-native.log`。只单播自有私有接收器，不改系统托盘。初轮夹具命中按钮边缘未触发点击，修订后按实测内部中心操作，未模拟回调成功。
- 热拔插移除来源任务栏时，即使光标仍在预览内也立即回收孤儿预览和 DWM 关系，不再靠不断续期的离开计时器维持顶层窗。
- TASK_PREVIEW 存档隔离真实夹具三轮保存/重载、普通 INFO 保留和仅栏时恢复 NORMAL 尺寸完整 PASS；日志 `D:/BlenderUI/build/shell-redesign-persistence2-native.log`。

- TASK_PREVIEW 存档夹具停用本测试进程的 idle-hover 服务，避免测试直接创建、没有悬停候选的预览按正常逻辑被关闭；保存/载入 handler 和真实窗口 RNA 仍照常运行。综合菜单/滚轮/两源 LIVE DWM/真实子菜单保活已完整复跑 PASS，真实 Programs 自动填充重绘截图也已确认。

- 预览点击绑定当时卡片的 HWND/PID/线程/启动时间/类名，不按后来刷新后的任务列表索引激活；任务关闭、重用或重新排序时精确匹配，否则取消并关闭，防止点 B 误激活 C 或旧第二张卡越界。说明页更新当前独立 AppBar/通知架构与兼容边界。

- AppBar 复查修正两处边界：物理栏定位仅改坐标并保留 z-order，防止高度/拓扑变化重新盖住全屏应用；模态交互期间不提前确认新显示拓扑，释放后会重试热插拔建栏/回收。新增 busy→release 断屏生命周期纯回归。

- 收紧 shell 生命周期：runtime 在可能关闭预览/菜单的服务之后重新枚举活窗口重绘，不再读取 tick 开头保留的旧 Area；预览窗右键关闭后立即返回，不继续访问已释放的当前 Window；通知图标退出/繁忙的右键回调改为可恢复报告。

- 开始列表异步同步后显式标记原生菜单重绘；真实索引夹具等待该重绘并断言 APP 按钮到达 RNA，而非只检查索引后台状态。辅助窗口存档隔离夹具扩展 TASK_PREVIEW 角色，预览同样不得污染普通文档窗口保存链。

- 原生 AppBar 实测完整通过：真实自有栏 56→80 逻辑高度预留工作区、自有正常窗口最大化避让、原生 fullscreen/generation 通知与 topmost 守门、退出恢复原工作区；日志 `D:/BlenderUI/build/shell-redesign-appbar-native.log`。未隐藏原系统栏、未移动外部窗口。
- 综合 GUI 已测通过 bar 外 TASK_CONTEXT/START_CONTEXT、两条自有窗口 DWM LIVE 登记及 NOACTIVATE、真实 UIList 滚轮可见项变化且 DPI/View2D 缩放不变；随后夹具访问被正常失焦关闭的 Start 旧 RNA 导致本 QA 进程退出，已定位为测试 retained window 引用，正在改 fresh token lookup 后复跑。此处不作为全套 PASS。

- 原生 GUI 发现普通悬停 UI handler 被全局模态守门误阻塞：新增 shell-only busy scope，并配合精确 native handler 状态分类，使开始列表、悬停预览和通知 RNA 能及时更新；正常 Node/Canvas 异步守门保持原样。开始原生夹具新增“索引完成后未输入/重开即自动显示条目”断言，通知区新增简繁本地化。待重编译实测。

- 根据 Open-Shell `MenuContainer.cpp` / `ProgramsTree.cpp` 的 Windows 7 双栏结构重新组织开始菜单：左侧独立滚动列表、固定/最近首页及可折叠 Programs 文件夹树，右侧用户与固定位置入口，搜索置底；不复制或链接 Open-Shell 代码。
- 新增纯内存层级 helper 与原生 UIList RNA 适配器；文件夹由已校验的相对路径推导、合并用户/公共相同文件夹，应用启动身份保持原样，停止 15 行分页设计。
- 新增固定 allowlist 的文档、图片、音乐、下载、计算机、控制面板入口；应用所在位置仅针对已索引项，重新校验路径/文件身份并持有读保护后打开所在文件夹。启动、最近记录及原子固定项持久化不变。
- 本轮改造开发中，子代理不启动 GUI、不构建、不提交；由主代理统一验证。
- 开始窗口默认改为 640×620，HOME 首页和左侧 21 行独立滚动 UIList、原位展开文件夹及返回操作、底部搜索与右侧用户/系统/关机区已接入；所有程序不再分页，绘制回调不重建 RNA 列表。旧二进制不支持独立 shell 窗时明确失败，不再降级到任务栏内裁剪弹窗。
- 新增文件夹合并/排序/展开/Unicode 身份/层级上限/首页去重/全局搜索纯测试，应用位置操作和固定系统位置入口也加入 mock 回归；UIList 类型注册兼容性测试同步更新，待执行。
- 展开身份只接受 SHA256 键且最多 8 层程序目录；行按钮保留整行宽度，将文字左对齐交给主代理的 shell-only 原生样式，避免仅文字区可点击。
- 39 项开始菜单纯测试已通过；`blui/START_MENU.md` 同步双栏、原位目录树、独立滚动、底部搜索和重新验证应用所在位置的新交互，明确 Open-Shell 仅为结构参考、不复制代码。GUI/构建仍待主代理统一执行。
- 搜索 RNA 回调在事件边界同步纯内存列表，输入时即可更新，不等待退出搜索框；保留当前索引列表引用防止缓存 `id` 重用，空索引正确显示无匹配项。
- 新增独立 `taskbar_options_ui.py` 外观 RNA 适配器：栏高 32–160、图标 16–64 逻辑像素，默认 56/32；回调只更新纯内存状态，并将高度不足时的规范值回写控件，不执行文件 IO。提供 values/sync、原生独立设置面板插槽、重置和注册接口，等待主代理与持久化服务集成。
- 新增 `test_taskbar_options_ui.py`，验证 RNA 参数范围、图标放大后的栏高规范、同步不重复保存/版本自增、嵌套回调抑制、只重绘 shell、重置及无窗口上下文；待执行。
- 外观 RNA 适配器 8 项纯测试全部通过；开始菜单 39 项仍全部通过，修改文件 AST 与 `git diff --check` 无错误。未执行 GUI、构建或 Git 提交。
- 开始菜单焦点关闭新增自有 START_APP 子菜单保护（必须同时匹配源 RNA 指针和 HWND）；窗口被显示器边界裁剪或 UIScale 较大时，左栏行数按实际逻辑高度自适应，右栏缩小空隙/行高并将次要位置折叠为“更多位置”，保留搜索与电源入口。
- 新增 `test_start_menu_layout.py` 覆盖 DPI 等比例、小屏/大字号裁剪、无结果占位、范围校验及正确子菜单/其他来源/已关闭子菜单的焦点关闭条件，待执行。
- 49 项开始菜单相关纯测试通过（原 39 项加响应式/子菜单身份 10 项）。更多位置只在实际逻辑高度不足时出现，常规双栏设计保持不变。
- 新增通知区纯协议边界 `notification_wire.py` 与异步客户端 `notification_client.py`：128 图标/4MiB 行上限，严格窗口身份和像素验证，Popen/所有 pipe IO/等待回收仅在自有线程；主线程只消耗内存并分批 8 项建立预览，回调只提交现有 key 的限定事件。关闭异步发 shutdown/EOF，只回收本 client 创建的 helper，保留 host 的自有窗口清理/恢复流程。尚待 UI 与测试。
- 通知区写管道与监督线程分离，避免 helper 卡住导致管道写满时无法回收；快照/回调 6 秒失效保护，关闭优先让 host 清理与恢复，超过 2 秒仅结束本客户端拥有的 Popen。
- 新增通知区原生 UI：默认最多 6 个 24px 逻辑槽位，隐藏/溢出图标进入独立 TASK_CHOOSER 通知区窗口，最多 128 项以原生 UIList 滚动；左键/双击/右键回调只提交已存在 key，helper 再次校验进程/窗口身份。draw 与 tooltip 只读 RAM，坐标只在明确点击时查询自有窗体。尚待回归与主代理集成。
- 新增 `test_notification_client.py` 协议和内存客户端测试：元数据/尺寸/像素/容量/重复身份、限定回调、每批 8 图标、RAM 重建、队列忙/失效/关闭、快照防外部修改与私有 QA 启动保护；不启动真实 helper。待执行。
- 通知区协议/客户端 13 项纯测试通过；新增 UI 6 项 mock 回归覆盖布局宽度、隐藏/溢出分槽、draw 无 IO、主 RNA 替换后重建、正常窗体禁止回调与 tooltip RAM 读取。仍未启动通知区 helper 或 GUI。
- 通知区读取器补 4MiB 有界读取回归；主客户端/协议 14 项、UI 6 项通过，连同 host/protocol/pixels 既有回归，本目录通知区测试共 43 项通过。子代理未执行 GUI、helper、构建或提交。
- 通知区 helper 启动显式 `-X utf8`，避免 Windows 管道使用 CP936 使中文 tooltip 破坏严格 UTF-8 协议；同时通知 host 代理将输出改为 UTF-8 字节写入。
- 新增仅主代理串行运行的 `check_notification_ui_native.py`：在自有 NORMAL HWND 上安装唯一注册消息回调并严格恢复，仅向本 client 的私有 helper PID/类/HWND 发送 NIM；8 项图标（含隐藏/溢出）、实际预览 ID/栏绘制、原生 LEFT/RIGHT 鼠标回调、独立通知区 UIList、DELETE/异步关闭与原布局保持。Fixture 禁用正常 runtime timer、自行 poll，绝不广播/隐藏系统栏/注册 AppBar/启动外部应用。客户端追加只读 helper_pid 供所有权核验。尚未由子代理运行 GUI。
- 新增原生 UI fixture AST 与 `git diff --check` 通过；43 项通知区纯测试仍通过。已交主代理执行，不新增未验证 hover 功能。
- 主代理原生通知区 UI 首跑已验证真实 8 项缓存与栏像素绘制，但原生 LEFT 回调未收到；fixture 增加不替代真实功能的 operator/poll/command/WNDPROC 诊断，并扫描按钮水平/垂直内部中心后点击，检查所选项 callback 与注册消息一致。等待主代理重跑。
- 原系统任务栏预留区移交（开发中）：参考 ManagedShell ExplorerHelper 的 ABM_SETSTATE AUTOHIDE 协调，新增 helper-only `taskbar_reservation.py` 独立有界/原子 UTF-8 NoBOM 恢复日志；先保存原可见任务栏及原 auto-hide 位，再释放系统栏占位，不调用 SPI_WORKAREA、不注销外部 AppBar、不移动外部窗口。原来已 auto-hide 不取消，恢复仅撤销本次置位并保留后来其它状态位。
- 主 guard 与第二 crash guardian 同时恢复 visibility 和 reservation，覆盖 hide 前崩溃、EOF/心跳超时/owner/helper 退出、新 Explorer epoch；每次写前复核真实 GetShellWindow PID/启动时间/线程/类及 Windows Explorer 路径，新 epoch 先写新身份，不用旧 HWND。外部 auto-hide 改动则停止隐藏并恢复自己记录的可见栏，不反复抢用户设置。
- AppBar 缓存键包含真实 monitor work rect，并增加纯内存 invalidate()，系统栏移交后重新 QUERY/SETPOS，但仍从 full monitor rect 提出高度，避免重复扣除预留区；GUI/native 由主代理统一验证，新增纯 mock 恢复回归待执行。
- reservation 首批 26 项与现有 AppBar 20 项纯回归 PASS；补充 workarea 移交/自身 work 变化无重复高度、显式 RAM invalidate 无 SETPOS 循环，以及 visibility 日志写失败也执行独立 auto-hide 回滚的回归。子代理未运行 GUI、未变更真实系统栏。
- reservation 27 项 + AppBar 22 项 + 旧 visibility/placement 18 项纯回归全部 PASS；更新 TASKBAR_APPBAR.md 的移交/恢复与协议文档。新增仅主代理串行执行的 `check_taskbar_reservation_native.py`，真实 fixture-owned guard hide→reclaim→自有 AppBar 单次占位→显式恢复→仅结束自有 helper 验证第二 guardian，失败保留未完成恢复日志；子代理只写未运行。
- Guard/第二 guardian 启动显式 `-X utf8`，避免 Windows CP936 错误信息破坏 UTF-8 status 协议；native crash 夹具在故意结束自有 helper 后允许正常 Pending 报告，并读取真实系统状态验证第二 guardian，而不是将期望的服务退出当成功恢复。
- 第二恢复进程在 Explorer 同时重启、primary HWND 暂时缺失时独立有界重试最多30秒，保持原子恢复意图与 session lock，不阻塞 BLUI/UI；新增 delayed Explorer recovery mock，替代原1秒恢复窗过短的边界。
- Desktop 原生生命周期（开发中）：新增仅 DESKTOP 使用的 BLUI_DesktopWindowClass（不含 OWNDC/CLASSDC），独立角色 marker+非零 atomic instance token；NCDESTROY/SETFOCUS fallthrough 均按精确 msg gate，意外父窗口销毁只置本窗失效并排队 force close，丢弃旧 size/paint/focus/key 事件，不触发 last-window quit。
- 桌面原生 OpenGL 窗预建自身隐藏同 pixel-format cleanup surface，parent loss 保留该 HGLRC 迁移至私有 DC，仅用于 queued GPU teardown；不拿普通窗口 context 删除私有 VAO/FBO，DropTarget/DC/DM/Wintab 保持独立释放，禁止失效 HWND 激活/resize/swap/draw。其它 backend 暂 fail-closed，普通窗口行为不改；native 尚未构建/运行。
- Desktop 临时 Node screen 增 SCREEN_BLUI_DESKTOP_HOST 精确位，orphan 清理要求 temp+标记+单 Node；已对该种私有 screen blend write 省略，普通 Node 不受影响，workspace layout writer 同步隔离待完成。未改进程 DPI awareness、不跨 awareness 强行 SetParent。
- workspace writer 使用局部序列化副本，仅过滤 temp+Desktop marker 的 private layout，并跳过被滤布局的 prev/next；不修改实时 RNA/list/普通 Node、保留所有普通 workspace 布局。失效 Desktop Wintab/鼠标 capture/主题 HWND 写及 drawable reset 增空句柄守门；本轮 C/C++ 仍待主代理构建/原生父窗口销毁实测。
- DESKTOP ctor 使用 SW_HIDE 初始创建、不将其设为 GHOST active window；只有 helper verified attach 后才 SHOWWINDOW，避免未挂载空白全屏 flash；normal/Taskbar/Start 的 ShowWindow/activation 保持不变。
- 仅 interactive DESKTOP+WS_CHILD 的真实 ButtonDown 对自有 HWND SetFocus，随后 WM_SETFOCUS 精确事件激活 Blender 窗状态；不在 hover/SHOWWINDOW/普通位置消息抢焦点，不改变 NOACTIVATE taskbar。
- 新增 `test_desktop_native_guards.py` 10 项源码守门，检查 exact msg/instance/hidden ctor/独立无 OWNDC class、只点击 child focus、保留 HGLRC 清理、丢弃非 Close 旧事件/禁止最后窗退出、失效 draw/swap 与 temp marked Node/layout 存档隔离；不替代主代理 native 编译/GUI。
- 10 项 Desktop native source guard PASS；新增 `check_desktop_native_lifecycle.py` 仅主代理串行运行，假 parent/child 均 exact 本进程 HWND，验证初始隐藏/instance更新/NCPAINT不误关闭、Layered child/click focus/Node A事件、parent death排队独立清理及存档重读后普通 Node 保留、Desktop私有layout/窗消失。子代理只写不运行，不接触 Explorer/外部窗口/任务栏。
- Native Desktop own-child QA 在安全销毁前存自有屏幕截图 `D:/BlenderUI/build/desktop-native-own-child.png` 供主代理验证真实渲染；SetWindowLongPtr/GetParent 明确 pointer-sized签名，所有 mutation前只读核验 own PID/thread/start/class/instance。夹具仍未由子代理运行。
- Native Node 键盘夹具仅模拟自有 window 内 region-center MOUSEMOVE 来设置 Blender area routing，不移动系统光标；真实 native ButtonDown/child focus 独立校验，防测试光标原来在外部窗口导致 A键被送入空区域。
- 主代理 native build PASS，Desktop own-child 首轮点击/真实GetFocus均通过，但A选择断言失败。源码定位是 fixture未给A键event_simulate传x/y：RNA每个事件无条件赋xy，默认0把键送到(0,0)边界而非Node region。夹具PRESS/RELEASE均显式传region-center坐标，断言前截图并打印native focus/actual event coords/region/select_all poll/selection；新增该API语义sourceguard，不直接执行select_all代替。等待主代理复跑，不把首轮失败计为PASS。
- 更新旧 shell UI sourceguard 为精确匹配 NORMAL+DESKTOP 双role保守分支，仍断言二者在精确 UI状态helper前直接 busy；不弱化正常或宿主Node树的 pointer/modal 安全守门。
- 主代理 Desktop own-child 原生复跑全部PASS（7.18秒）：真实focus+A选择、own-parent death清理/普通Node保留、save/open不泄露Desktop UI，截图确认实际canvas渲染。原焦点未改，仅修fixture键坐标。
- 托盘hover被动窗新增最小 opt-in no_activate=False 创建参数，仅 TASK_CHOOSER 接受；复用DNA原padding同尺寸runtime int并读Blend归零，独立GHOST passive flag设置 NOACTIVATE/SW_SHOWNOACTIVATE且不置GHOST active，不借AppBar flag、默认普通chooser/其他role不变。taskbar_windows.create只加该参数，其它focus/draw集成主代理负责。
- 新增 `notification_hover.py`：fresh taskbar native hover button读取真实通知key，RAM元数据身份+支持action精确验证，350ms debounce后ENTER、离开/关闭/cancel仅LEAVE一次；UIA/display不伪造Hover。Tip为独立no-activate TASK_CHOOSER/NOTIFICATION_TIP，native instance property+exact PID/thread/start/class与RAM owner共同守门，仅回收自己的提示，不关闭其它chooser/Start/context/Desktop/正常窗；existing菜单/preview期间不显示。draw只读已准备RAM行/图标，不做Win32或I/O，新UImsgid复用既有翻译。
- hover稳态缓存几何，不随每帧mouse位置连续移动/重排提示 HWND；新增纯mock/sourceguard测试覆盖debounce/真实action allowlist/LEAVE once/切换icon/历史UIA+系统控制不伪造hover/身份复用/菜单接管/关闭取消/保守busy/Unicode/坐标协议上限/draw仅RAM/passive opt-in读档归零，待执行。
- hover 17 项 mock/sourceguard PASS；新增主代理只跑的 `check_notification_hover_native.py`，仅 private OWN source/receiver真实NIM/version4协议，native hit-test+模拟自有窗口指针（不移动系统光标）→真实ENTER/NIN_POPUPOPEN→独立 NOACTIVATE Tip/截图→LEAVE/NIN_POPUPCLOSE恰一次→owned helper/窗口清理；不广播、不改Explorer/系统栏、不发送外部app回调。子代理只写未运行。
- Desktop lifecycle 新增独立只读 `blui_has_desktop_interaction` getter，复用精确 UI 状态 helper，仅 unpressed HIGHLIGHT/EXIT 不阻塞；真实 modal OP、未知 modal handler、popup/text/numeric/wait/drag、管理器 drags、当前原生按键/capture/cursor grab 仍阻塞。旧 `blui_has_modal_interaction` 与 runtime Node/thumbnail/session 守门完全不改，未增加/改变 DNA 字段；RNAWindows.busy() 仅生命周期使用新 getter，旧二进制保守 fallback。待纯回归及主代理增量构建/真实 hover restore。
- 新增 `test_desktop_interaction.py` 纯 AST adapter 与 native source guards：普通 NORMAL/DESKTOP hover 放行生命周期但旧 guard 保留；任何真实编辑/path drag/旧 binary fail-closed；精确 handler 类型、五类实时物理按键/capture/grab、只读 getter 与 runtime 原 Node gate 不变。原生源已交主代理增量构建，子代理不运行 GUI。
- desktop 精确 getter 相关 24 项纯测试 PASS（新增8项+原shell5项+原生生命周期11项）。新增仅主代理运行 `check_desktop_hover_restore_native.py`：真实 OWN capture/Node box modal 必须 busy；自有 Calculator 的原生 HIGHLIGHT 必须旧 Node gate=True、新 lifecycle=False；实际 RESTORE ack后8秒内关闭私有DESKTOP、保留普通窗口/布局并恢复原icons；输入坐标全部显式且仅owned窗口，失败保留恢复journal。仅写未运行。
- 真实 hover_restore 夹具保存原UI线程DPI后发现生产 DESKTOP 创建 PMv1 与 Explorer PMv2 不同，之前 host/service 夹具的 helper-only DesktopWindows 构造改变线程上下文掩盖了问题；先前兼容实测不作为生产 DPI 证据。新增独立 `GHOST_BluiDesktopDpiWin32.hh` creation-only RAII：只读验证 GetShellWindow 的真实 Windows Explorer 路径/PID/启动时间/线程/唯一 Progman或WorkerW→DefView→ListView链，用 verified host 的 window DPI context 创建 DESKTOP，ctor后始终还原旧线程context；普通窗口和 process DPI 不改，helper 严格比较不放宽。待主代理增量构建重测。
- DPI scope 使用已加载系统 User32 的四个 DPI API（GetModuleHandle/GetProcAddress，有缺失 fail-closed），保持项目现有 Win8 API target 宏，不改全局SDK版本、不加载第三方Shell DLL；原生代码已完成交主代理编译，夹具正在补创建前后原thread/normal HWND context不变断言。
- 新增私有夹具 helper `qa_desktop_dpi.py`：helper-only discovery/snapshot临时上下文始终恢复，记录并逐阶段断言原UI thread和所有NORMAL HWND context/身份原样；host/service/hover原生夹具全部接入，DESKTOP窗口创建必须从原UI context调用且与真实host context相同。own-parent lifecycle仅新建自有STATIC父窗时短暂匹配已创建Desktop context后恢复，解决同进程SetParent异DPI失败；不改变已有NORMAL/process DPI，夹具仅写待主代理执行。
- DPI创建scope编译PASS；原始UI线程hover夹具已真实挂载、OWN capture+Node select_box守门PASS。源码确认 button_modal_state不含普通HIGHLIGHT，因此旧getter=True并非每次普通悬停的前提，修正此错误QA断言；夹具增加仅OWN child真实点击/focus、实际draw后view_all、view-space node bounds/target坐标诊断及悬停前后截图，新lifecycle必须False且RESTORE成功，旧严格gate由sourceguard保证不变。未mock getter/hover，待主代理复跑看图。
- 新增 `test_desktop_dpi_scope.py` 只读 native source guards及私有fixture helper纯mock：DESKTOP-only scope/ctor后恢复/Win8 target API动态加载/Windows Explorer路径+epoch+唯一bounded父链/不放宽helper兼容/全部夹具恢复原UI context；另验证异常时worker context还原、仅自有新fakeparent可匹配、不掩盖已有NORMAL context改动。子代理不运行原生GUI。
- 原始UI PMv1→新Desktop/Explorer PMv2且原UI/Normal原样的真实hover+RESTORE全部功能PASS，唯一QA退出失败为 temp目录cleanup与仍在发布空journal的独立guardian竞态。三个host/service/hover夹具结束前明确校验原icons、恢复ack/空journal（shell=None/canvases=[]），成功和失败都保留自身小型QA目录，禁删仍有guardian的目录；不忽略恢复状态、不删系统数据。新DPI mock修正其_identity双参数stub，待重跑。
- DPI source/fixture新增11项与原native11项+interaction8项共30项纯回归全部PASS；主代理preserved-context service双屏两轮、host显式恢复+own-helper死亡独立恢复、own-parent focus/死亡/save-open全PASS（原UI/Normal context18、新Desktop/Host34）。DESKTOP_HOST文档补creation-only RAII及旧夹具DPI证据纠正，保留Win11/Win+D/真实Explorer restart未证实边界；hover功能已PASS并视检真实按钮灰高亮，保留诊断目录的最终exit0待主代理复跑。全部子代理源码冻结，无GUI/build/Git操作。
- 主代理最后hover重跑停在actual RESTORE后，所属journal已空且helper存活；未按猜测改native。私有夹具补20秒重复faulthandler线程栈、RESTORE前后/timer return/runtime tick/最终状态与journal/native originals gate/close逐边界诊断，controller只读已发布RAM不加锁、不查询外窗用于打印。用于区分operator、own window close、timer外GHOST或测试收尾挂起；子代理不操作任何进程/GUI。
- package hover原生堆栈明确phase3/4 screenshot→WM_redraw_windows→background._draw，不是close；PYTHONMALLOC=debug复现“allocator called without holding the GIL”。定位 legacy PyC_IsInterpreterActive 用PyThreadState_GetDict误当当前线程持锁，另一worker可让其误判且GetDict自身会分配；主代理正式修为Py_IsInitialized&&PyGILState_Check（CPython3.10原文及实现核验）。实际3处conditional消费者与generic诊断调用契约兼容，原pyop Save/RestoreThread及callback Ensure/Release保留、不关background回调、不弱化Node守门。
- 新增 `test_python_gil_guard.py` focused source回归，检查真正持锁predicate/3锁consumer/allocator保护区间/pyop释放与draw重新获取GIL/真实screenshot+background保留；私有hover夹具新增BLUI_DESKTOP_QA_SCREENSHOTS=2默认、4或8有界真实截图总次数，用于主代理debugmalloc重测，子代理不运行GUI/build/进程操作。
- GIL focused8项纯回归全部PASS，默认总2/压力4或8截图夹具AST PASS已冻结；主代理正式GIL修复编译、新stage在PYTHONMALLOC=debug下原hover/RESTORE与own-parent死亡/save-load完整PASS，正在压力8截图与普通路径复验。DESKTOP_HOST同步根因、CPython契约与真实已通过范围，不把此锁修复冒称消除所有graphics/外部shell-hook/COM挂起。
