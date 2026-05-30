# Startup Sound Changer

一个 Windows 小工具，用来换开机声音，也顺手支持关机声音。

界面很简单：打开后选择“设置开机音”或“设置关机音”，可以从内置预设里选，也可以选择自己的音频文件。

## 功能

- 修改 Windows 启动声音资源。
- 提供一些旧版 Windows 启动声音预设。
- 支持设置关机声音。
- 关机声音使用一个 Windows Service 配合用户会话里的轻量 helper，在关机或重启前尽量播放完整。
- 预览音频在单独线程里播放，播放中会禁用预览按钮，避免界面卡住或重复预览。
- 删除关机音时会清理音频、配置、helper 和 service。

## 说明

开机声音和关机声音不是同一种实现。

开机声音会修改系统的启动声音资源，所以程序需要管理员权限。

从 Windows 8 开始，系统已经没有稳定的传统关机声音入口。这个工具的关机声音实现不是替换系统文件，也不是拦截电源按钮，而是在系统准备关机或重启时，尽量争取一小段时间播放你选择的声音。普通从开始菜单、快捷键菜单或命令发起的关机/重启通常可以触发；强制关机、断电、长按电源键、系统更新、音频服务异常或 Windows 等待超时，仍然可能导致声音没响或没播完整。

## 音频版权

仓库里的 Windows 预设音频版权属于 Microsoft。它们只作为怀旧和个人使用场景下的预设素材放在这里。这个项目本身不主张拥有这些音频的版权。

如果你要重新分发、商用或打包到别的项目里，请自己确认相关授权和风险。

## 构建

需要：

- Windows
- Python 3.12
- Go
- PowerShell

安装依赖并打包：

```powershell
scripts\build.ps1
```

如果你已经建好了 `.venv` 并安装过依赖：

```powershell
scripts\build.ps1 -SkipVenv
```

构建完成后主程序在：

```text
dist\startup-sound-changer.exe
```

## 开发结构

```text
app.py                         程序入口
startup_sound_changer\          Python GUI 和系统修改逻辑
helper-go\main.go              用户会话里的关机声音 helper
service-go\main.go             Windows Service
windows-sounds\                开机声音预设
shutdown-sounds\               关机声音预设
startup_sound_changer.spec      PyInstaller 配置
scripts\build.ps1              构建脚本
```

## 备注

这是一个偏个人使用的小工具，不保证覆盖所有 Windows 版本、系统策略和关机路径。使用前建议确认系统还原点或备份策略，尤其是修改启动声音资源时。
