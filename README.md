# 常客 AI Windows（最新版源码）

本仓库保存常客 AI 的最新 Windows 源码、翻译/去重功能、贴纸 GIF 功能、补丁入口和在线更新器。

## 本次本地模型修复

团队共享包无法识别的原因是旧核心把 `asr_parallel=10` 直接传给 Whisper 的 `num_workers`，会复制十份模型；没有 NVIDIA 或显存不足时就会启动失败。`patch_sticker_22/patched_entry.py` 现在会：

- 先检测可用的 CUDA 设备；
- 有 CUDA 时使用 `cuda/int8_float16`，不可用或加载失败自动使用 `cpu/int8`；
- 始终只加载一个 Whisper 模型实例，并从本地 `models_cache` snapshot 解析模型路径；
- 模型仍缺失时给出明确错误，不会假装翻译成功。

完整模型包（约 3.36GB）不提交到 GitHub：GitHub 普通仓库单文件限制为 100MB，模型和 CUDA 运行库也不适合放进代码历史。`发布清单.json` 记录了本机完整包的 SHA256，团队应使用桌面上的完整压缩包，解压后双击 `常客AI2.2/常客AI2.2.exe`，不要只复制 exe。

## 开发运行

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe translator_desktop.py
```

源码仓库不含模型、FFmpeg、CUDA、Ollama 和任何 API Key。首次运行前准备 `models_cache`、FFmpeg，并在本机创建 `deepseek_api_key.txt` 或设置 `DEEPSEEK_API_KEY`。

## 构建与更新

使用 `build_desktop_201.spec` 构建桌面程序；使用 `patch_sticker_22/build_patched.spec` 构建带贴纸增强的核心。团队更新器相关文件在 `online_updater.py`、`常客AI在线更新.bat` 和 `online_updater.spec`。

真实密钥、个人视频、贴纸、缓存、模型权重和构建产物均不会进入仓库。
