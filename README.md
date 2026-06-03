# 谁动了我的电脑

Windows 本机防误动与行为记录工具。项目提供两种透明可见的监控模式：被触碰后锁屏拍照、持续截图/拍照与活动记录。

作者：by-装纯研习社  
微信：BAIY_13  
官网：www.zcyai.cn

## 功能

- 模式一：检测键盘或鼠标活动后保存照片/截图并调用 Windows 锁屏。
- 模式二：定期截图、尝试摄像头拍照，并记录窗口与输入活动。
- 输出方式：本地保存或 SMTP 邮件发送。
- 设置中心：保存路径、图片格式、邮箱、截图频率、摄像头频率、存储上限。
- 快捷键：支持自定义启动模式、停止、保存、打开目录、导出日志、刷新。
- 记录查看：显示事件、中文说明、预览、打开文件、删除文件。
- 隐私保护：不保存具体按键内容，仅记录键盘活动发生。

## 合规说明

本项目只适合在本人拥有或已获得明确授权的 Windows 设备上使用。软件界面透明可见，不提供隐藏运行、绕过权限、隐蔽采集或未授权监控能力。

## 目录

```text
outputs/who_touched_my_pc/
  app.py                 主程序
  requirements.txt       Python 依赖
  config.example.json    示例配置
  run.ps1                从源码运行
  build_exe.ps1          打包 exe
```

运行过程中生成的 `config.json`、`logs/`、`captures/`、`build/`、`dist/` 和 `*.exe` 不进入 Git。

## 运行源码

需要 Windows 和 Python 3.11+。

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

生成文件位于：

```text
outputs/who_touched_my_pc/dist/谁动了我的电脑.exe
```

## 邮箱配置

复制 `outputs/who_touched_my_pc/config.example.json` 为 `config.json`，或直接在软件设置页填写 SMTP 信息。真实邮箱、授权码和运行日志默认被 `.gitignore` 排除。

## 开源协议

MIT License。详见 [LICENSE](LICENSE)。
