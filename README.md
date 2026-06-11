# 白泽混剪

白泽混剪是一款基于 [MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo) 二次开发的 AI 短视频生成与桌面混剪工具。它可以根据主题或自定义文案自动生成脚本、搜索素材、生成旁白、制作字幕、添加背景音乐，并合成为适合发布的短视频。

当前分支重点面向本地桌面使用：保留 WebUI 与 API 能力，同时提供 Electron 桌面壳，支持打包成 Windows 可执行应用。

## 功能特性

- AI 文案生成：支持 OpenAI 兼容接口、Groq、Qwen、DeepSeek、Ollama 等 LLM Provider。
- 素材获取：支持 Pexels、Pixabay 和本地视频/图片素材。
- 视频合成：支持横屏、竖屏、不同拼接方式、转场、背景音乐与字幕样式。
- 字幕生成：支持普通时间轴字幕，也支持 Whisper 转写字幕。
- VoxCPM 旁白：桌面端只保留 OpenBMB VoxCPM 声音克隆，不再依赖本地 TTS 服务地址。
- 内置音色：提供上传参考音频克隆、温柔女声、清亮女声、沉稳男声、纪录片旁白、新闻播报等 VoxCPM 预设。
- 桌面应用：通过 Electron 封装本地 WebUI，双击 exe 即可打开桌面窗口。

## 项目来源

本项目基于 `harry0703/MoneyPrinterTurbo` 二次开发，保留原项目 MIT License。感谢原作者和开源社区提供的基础能力。本分支主要针对中文桌面端使用体验、VoxCPM 声音克隆、生成流程和打包方式进行了调整。

## 环境要求

- Python 3.11 到 3.12
- 推荐使用 [uv](https://github.com/astral-sh/uv) 管理 Python 环境
- Windows 10/11、macOS 或 Linux
- FFmpeg，用于音视频合成
- 首次使用 VoxCPM 时需要下载 `openbmb/VoxCPM2` 模型
- CPU 可以运行，但 VoxCPM、Whisper 和视频生成建议使用独显或性能较好的机器

## 快速开始

### 1. 克隆项目

```powershell
git clone https://github.com/1wanganshi/baize-fast-mix-video.git
cd baize-fast-mix-video
```

### 2. 安装依赖

```powershell
uv python install 3.11
uv sync --frozen
```

如果没有安装 uv，也可以使用 pip：

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

### 3. 创建配置文件

```powershell
copy config.example.toml config.toml
```

打开 `config.toml`，至少配置：

- `llm_provider`
- 对应模型服务的 API Key
- `pexels_api_keys` 或 `pixabay_api_keys`
- 如需本地素材，可在界面中选择本地上传

不要把 `config.toml` 提交到 GitHub。项目已经默认忽略该文件。

### 4. 启动 WebUI

Windows：

```powershell
.\webui.bat
```

macOS / Linux：

```bash
uv run streamlit run ./webui/Main.py --browser.gatherUsageStats=False
```

### 5. 启动 API 服务

```bash
uv run python main.py
```

默认 API 文档地址：

```text
http://127.0.0.1:8080/docs
```

## 桌面端开发与打包

Electron 桌面壳位于 `packaging/electron`。

### 本地启动桌面端

```powershell
cd packaging/electron
npm install
npm run start
```

### 打包 Windows exe

```powershell
cd packaging/electron
npm run dist
```

打包产物会输出到：

```text
dist/electron
```

注意：桌面包会启动内置本地 WebUI 后端。打包时请不要携带个人 `config.toml`、任务缓存、日志、模型文件和虚拟环境中的敏感数据。

## VoxCPM 说明

本项目的桌面端 TTS 只保留 VoxCPM：

- 使用 Python 包 `voxcpm` 直接加载 `openbmb/VoxCPM2`
- 不依赖 `http://127.0.0.1:8000/v1` 这类本地服务地址
- 支持上传参考音频进行声音克隆
- 支持几个内置风格音色作为快速生成选项

参考音频建议：

- 单人声
- 无背景音乐
- 音质清晰
- 建议 5 到 20 秒
- 支持 wav、mp3、m4a、flac 等常见音频格式

如果 VoxCPM 报错，请先检查：

- 是否已经安装 `voxcpm`
- 模型是否下载完整
- 参考音频是否可读
- Python 版本是否兼容
- 当前机器内存或显存是否足够

## 常见问题

### 生成速度慢

视频生成速度受 LLM、素材下载、TTS、Whisper、视频编码共同影响。建议：

- 使用较快的 LLM Provider
- 优先使用本地素材或降低素材分辨率
- 关闭不必要的 Whisper 转写
- 使用硬件编码，例如 `h264_nvenc`、`h264_qsv`、`h264_amf`
- VoxCPM 首次加载模型会比较慢，后续会复用缓存

### 找不到 FFmpeg

请安装 FFmpeg，并在 `config.toml` 中配置 `ffmpeg_path`，或确保 `ffmpeg` 已加入系统 PATH。

### Pexels / Pixabay 搜不到素材

请检查 API Key 是否有效，或者改用本地素材上传。

### 桌面应用看起来像网页

桌面端使用 Electron 封装本地 WebUI。用户只需要双击 exe 打开桌面窗口，内部会自动启动本地后端，不需要手动打开浏览器。

## 开源协议

本项目基于 MIT License 开源。原始项目版权归 MoneyPrinterTurbo 原作者及贡献者所有，二次开发部分同样遵循 MIT License。

## 免责声明

请遵守你所在地区的法律法规和第三方平台规则。生成内容、素材版权、声音克隆授权和发布行为由使用者自行负责。不要上传或克隆未经授权的个人声音。
