# mac-hid-toolkit

macOS HID 设备增强工具集，包含两个功能：

1. **蓝牙遥控器映射** — AB Shutter3 单按钮通过手势识别（单击/双击/长按）映射为自定义键盘/鼠标/Shell 动作
2. **Dell 显示器音量控制** — 键盘音量键通过 DDC/CI 直接控制 Dell 显示器扬声器音量，带屏幕 HUD 浮窗显示

两个功能集成在一个进程中，通过 LaunchAgent 开机自启。

## 功能

### 蓝牙遥控器 (AB Shutter3)

通过 IOKit HID 设备级过滤，精确识别 AB Shutter3 遥控器，不干扰键盘媒体键。

| 手势 | 默认动作 | 可配置 |
|------|----------|--------|
| 单击 | ↓ Down Arrow | ✓ |
| 双击 | ↑ Up Arrow | ✓ |
| 长按 | Enter | ✓ |

支持三种动作类型：

```json
{"type": "key",   "key": "f", "modifiers": ["cmd"], "description": "Cmd+F"}
{"type": "mouse", "button": "left",                  "description": "鼠标左键"}
{"type": "shell", "command": "open -a Safari",        "description": "打开 Safari"}
```

### Dell 显示器 DDC 音量

自动检测当前音频输出设备 — 只有输出到 Dell 显示器时才拦截音量键，切换到耳机/其他设备后音量键恢复正常。

- F12 / 音量+ → Dell 音量 +5%
- F11 / 音量- → Dell 音量 -5%
- 静音键 → 切换静音
- 屏幕 HUD 浮窗实时显示当前音量

## 安装

```bash
# 克隆
git clone https://github.com/punkpurin/mac-hid-toolkit.git
cd mac-hid-toolkit

# 创建虚拟环境
python3 -m venv .venv
.venv/bin/pip install pyobjc

# 安装 m1ddc（Dell 音量控制需要）
brew install m1ddc

# 授权辅助功能
# 系统设置 > 隐私与安全性 > 辅助功能 > 添加 python3 二进制
```

## 使用

```bash
# 手动运行
./run.sh

# 安装开机自启（LaunchAgent）
cp com.david.remote-control.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.david.remote-control.plist

# 重启服务（改完配置后）
launchctl kickstart -k gui/$(id -u)/com.david.remote-control

# 停用
launchctl unload ~/Library/LaunchAgents/com.david.remote-control.plist

# 查看日志
tail -f remote.log
```

## 配置

编辑 `config.json`：

```json
{
  "single_click":  { "type": "key", "key": "down",   "modifiers": [], "description": "↓ 下箭头" },
  "double_click":  { "type": "key", "key": "up",     "modifiers": [], "description": "↑ 上箭头" },
  "long_press":    { "type": "key", "key": "return",  "modifiers": [], "description": "Enter 回车" },
  "double_click_interval": 0.4,
  "long_press_threshold": 0.5
}
```

### 配置示例

<details>
<summary>PPT 翻页遥控器</summary>

```json
{
  "single_click":  { "type": "key", "key": "right",  "modifiers": [], "description": "下一页" },
  "double_click":  { "type": "key", "key": "left",   "modifiers": [], "description": "上一页" },
  "long_press":    { "type": "key", "key": "escape",  "modifiers": [], "description": "退出演示" }
}
```
</details>

<details>
<summary>视频播放控制</summary>

```json
{
  "single_click":  { "type": "key", "key": "space",  "modifiers": [], "description": "播放/暂停" },
  "double_click":  { "type": "key", "key": "right",  "modifiers": [], "description": "快进" },
  "long_press":    { "type": "key", "key": "f",      "modifiers": ["cmd"], "description": "全屏" }
}
```
</details>

<details>
<summary>截屏/录屏</summary>

```json
{
  "single_click":  { "type": "key", "key": "3", "modifiers": ["cmd", "shift"], "description": "截屏" },
  "double_click":  { "type": "key", "key": "5", "modifiers": ["cmd", "shift"], "description": "录屏面板" },
  "long_press":    { "type": "shell", "command": "open -a 'Photo Booth'",       "description": "Photo Booth" }
}
```
</details>

### 可用按键

<details>
<summary>完整按键列表</summary>

**字母**: `a`-`z`

**数字**: `0`-`9`

**功能键**: `f1`-`f15`

**特殊键**:
`return`/`enter`, `tab`, `space`, `delete`, `forwarddelete`, `escape`/`esc`,
`left`, `right`, `up`, `down`, `home`, `end`, `pageup`, `pagedown`

**修饰键** (用于 `modifiers` 数组):
`cmd`/`command`, `shift`, `alt`/`option`, `ctrl`/`control`

**符号**: `-`, `=`, `[`, `]`, `\`, `;`, `'`, `,`, `.`, `/`, `` ` ``

</details>

## 工作原理

### 遥控器映射

```
AB Shutter3 BLE → IOKit HID Manager (设备级过滤: 248A:8266)
                                      ↓ 记录时间戳
macOS NX_SYSDEFINED (code=0) → CGEventTap 检查时间戳
  → 100ms 内有 HID 报告 → 拦截 → 手势识别 → 执行动作
  → 无 HID 报告 → 来自键盘 → 检查 Dell 音频输出 or 放过
```

### Dell 音量控制

```
键盘 F11/F12 → NX_SYSDEFINED (code=0/1)
  → 当前音频输出是 Dell? → m1ddc DDC 命令 + HUD 浮窗
  → 不是 Dell? → 原样放过 (系统音量正常)
```

## 前置条件

- macOS (Apple Silicon)
- Python 3 + pyobjc
- `m1ddc` (Dell DDC 控制)
- 辅助功能权限 (CGEventTap)

## 文件结构

```
├── remote_control.py   # 主程序（遥控器 + Dell 音量）
├── volume_hud.py       # 音量 HUD 浮窗
├── monitor_hid.py      # HID 信号探测工具（调试用）
├── config.json         # 遥控器映射配置
├── run.sh              # 启动脚本
└── dell_volume.py      # Dell 音量独立版（未使用，已集成到主程序）
```
