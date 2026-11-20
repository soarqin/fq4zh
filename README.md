# First Queen IV Windows 版繁体中文移植

本项目将 DOS 版的官方繁体中文文本移植到 Windows 日文版 v1.10。使用自行准备的原版游戏文件，可以构建中文版游戏或单文件补丁工具。构建产物默认写入本地的 `dist` 目录。

## 构建准备

在 Windows 上准备 Python 3.9 或更新版本，以及以下两个原版游戏目录。

- Windows 日文版 v1.10 的完整游戏目录。
- DOS 官方繁体中文版的游戏目录。

构建脚本会校验 Windows 版 `fq4.exe` 和 DOS 版 `MAIN.EXE`、`FQ4MES` 的 SHA-256。

在仓库根目录安装 Python 依赖。

```powershell
python -m pip install pefile
```

## 构建

从仓库根目录运行构建命令。`--win` 和 `--dos` 都是必填参数，分别指定 Windows 版和 DOS 版的游戏目录。将示例中引号内的文字替换为实际路径。

### 构建中文版游戏

```powershell
python .\tools\build.py --win "Windows 版目录" --dos "DOS 版目录"
```

默认在 `dist\FQ4` 生成中文版 `fq4.exe`，并复制 Windows 原版的游戏资源到该目录。

### 构建单文件补丁工具

安装 MSVC x86 C++ 工具链和 Windows SDK。在 Visual Studio 的 x86 本机工具命令提示符中进入仓库根目录，再运行下面的命令。

```bat
python .\tools\build_patcher.py --win "Windows 版目录" --dos "DOS 版目录"
```

默认生成 `dist\FQ4ChinesePatch.exe`。补丁数据内置于工具，生成的 EXE 可直接运行。

## 使用

### 运行中文版游戏

构建完成后，进入 `dist\FQ4`，双击 `fq4.exe`。

### 使用单文件补丁工具

双击生成的 `dist\FQ4ChinesePatch.exe`，通过「浏览…」选择 Windows 日文版 v1.10 的 `fq4.exe`，再选择一种方式。

- 「生成中文版 EXE」在原版游戏目录生成 `fq4.zh.exe`，可双击启动。已有同名文件时，工具会复用内容相同的文件，或提示先重命名内容不同的文件。
- 「以内存补丁启动」立即启动游戏，汉化仅在本次运行中生效。游戏从原版目录读取资源和存档。

## 游戏手册

用浏览器打开本地 HTML 手册，可离线查阅剧情、游戏操作和快捷键。[繁體中文遊戲手冊](docs/FQ4-manual-zh-Hant.html)
