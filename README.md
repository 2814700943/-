# 谁动了我的电脑

![Platform](https://img.shields.io/badge/platform-Windows-0A66C2)
![Python](https://img.shields.io/badge/python-3.11+-3776AB)
![License](https://img.shields.io/badge/license-MIT-green)
![UI](https://img.shields.io/badge/UI-CustomTkinter-1F6FEB)

一个面向 Windows 的可见式防误动与行为记录工具。  
当电脑在离开工位后被他人操作时，它可以按设定自动锁屏、截图、拍照，并把记录保存到本地或发送到邮箱。

作者：by-装纯研习社  
微信：`BAIY_13`  
官网：[dn.zcyai.cn](https://dn.zcyai.cn)

## 下载

- 最新版本：[GitHub Releases](https://github.com/2814700943/-/releases/latest)
- 当前发布：`v2.3.1`
- Windows 可执行文件：`谁动了我的电脑.exe`

## 核心特性

| 模块 | 说明 |
| --- | --- |
| 模式一 | 检测到键鼠活动后立即锁屏，并尝试截图 / 拍照 |
| 模式二 | 按设定频率持续截图、拍照，并记录窗口活动 |
| 本地保存 | 保存截图、照片、日志到本地目录 |
| 邮件发送 | 通过 SMTP 把记录发送到指定邮箱 |
| 最近记录 | 支持详情查看、打开文件、删除附件 |
| 快捷键 | 支持启动、停止、保存、导出、刷新等操作 |
| 隐私策略 | 不记录具体按键内容，仅记录事件发生 |

## 项目截图

### 首页

![首页](docs/screenshots/home.png)

### 设置中心

![设置中心](docs/screenshots/settings.png)

### 帮助文档

![帮助文档](docs/screenshots/help.png)

## 适用场景

- 办公室临时离开工位，希望有人碰电脑时立刻锁屏并留证
- 宿舍、工作室、共享环境中，希望记录电脑被碰动的情况
- 想把证据保留在本地，或自动发到邮箱
- 想使用一个可见、可停止、可配置的 Windows 记录工具

## 运行环境

- Windows 10 / 11
- Python 3.11+
- 摄像头可选

核心依赖：

- `Pillow`
- `opencv-python`
- `customtkinter`

## 快速开始

在仓库根目录运行：

```powershell
.\run.ps1
```

或进入源码目录运行：

```powershell
cd .\outputs\who_touched_my_pc
.\run.ps1
```

## 打包 EXE

```powershell
.\build_exe.ps1
```

输出目录：

```text
outputs/who_touched_my_pc/dist/
```

## 配置说明

项目支持在界面中直接配置，也可以从示例配置初始化：

```text
outputs/who_touched_my_pc/config.example.json
```

主要可配置项：

- 保存目录
- 图片格式
- 输出方式（邮箱 / 本地）
- 模式一闲置阈值
- 截图间隔
- 摄像头拍照间隔
- 本地文件上限
- SMTP 邮箱信息
- 自定义快捷键

## 目录结构

```text
.
├─ README.md
├─ CHANGELOG.md
├─ CONTRIBUTING.md
├─ SECURITY.md
├─ LICENSE
├─ run.ps1
├─ build_exe.ps1
├─ docs/
│  └─ screenshots/
└─ outputs/
   └─ who_touched_my_pc/
      ├─ app.py
      ├─ requirements.txt
      ├─ config.example.json
      ├─ README.md
      ├─ run.ps1
      └─ build_exe.ps1
```

## Git 忽略策略

以下内容默认不会进入仓库：

- 真实配置：`config.json`
- 运行日志：`logs/`
- 截图和照片：`captures/`
- 打包产物：`build/`、`dist/`、`*.exe`
- 本地缓存：`__pycache__/`

## 合规与使用边界

本项目仅适用于：

- 本人拥有的设备
- 已获得明确授权的设备

本项目不提供：

- 隐藏运行
- 绕过权限
- 未授权后台监控
- 键盘内容窃取

界面和功能均以可见、可配置、可停止为前提。

## 相关文档

- 变更记录：[CHANGELOG.md](CHANGELOG.md)
- 贡献说明：[CONTRIBUTING.md](CONTRIBUTING.md)
- 安全说明：[SECURITY.md](SECURITY.md)

## 开源协议

MIT License，见 [LICENSE](LICENSE)。
