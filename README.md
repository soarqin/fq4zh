# First Queen IV Windows 版简繁中文移植

本项目将 DOS 版的官方繁体中文文本移植到 Windows 日文版 v1.10，并提供使用大陆常用术语的简体中文版。使用自行准备的原版游戏文件，可以构建中文版游戏或单文件补丁工具。构建产物默认写入本地的 `dist` 目录。

## 构建准备

在 Windows 上安装 uv。构建中文版游戏或重新生成补丁数据时，还需准备以下两个原版游戏目录。[uv 安装说明](https://docs.astral.sh/uv/getting-started/installation/)

- Windows 日文版 v1.10 的完整游戏目录。
- DOS 官方繁体中文版的游戏目录。

构建脚本会校验 Windows 版 `fq4.exe` 和 DOS 版 `MAIN.EXE`、`FQ4MES` 的 SHA-256。

项目需要 Python 3.9 或更新版本。首次运行构建命令时，uv 会创建项目环境，并按 `uv.lock` 安装依赖。也可在仓库根目录运行 `uv sync --locked` 提前准备环境。

## 构建

从仓库根目录运行构建命令。使用原版游戏文件构建时，必须通过 `--win` 和 `--dos` 指定 Windows 版和 DOS 版的游戏目录。将示例中引号内的文字替换为实际路径。

### 构建中文版游戏

```powershell
uv run --locked python .\tools\build.py --win "Windows 版目录" --dos "DOS 版目录"
```

默认构建繁体版，输出目录为 `dist\FQ4`。构建简体版时加入 `--locale zh-CN`，输出目录为 `dist\FQ4-zh-CN`。

```powershell
uv run --locked python .\tools\build.py --win "Windows 版目录" --dos "DOS 版目录" --locale zh-CN
```

每个输出目录都包含中文版 `fq4.exe` 和复制的游戏资源。游戏内简体使用黑体（SimHei），属于 Windows 的简体中文补充字体。游戏内繁体使用微软正黑体。

### 构建单文件补丁工具

安装 MSVC x86 C++ 工具链和 Windows SDK。在 Visual Studio 的 x86 本机工具命令提示符中进入仓库根目录，再运行下面的命令。

```bat
uv run --locked python .\tools\build_patcher.py --payload-dir .\patches
```

编译使用 `patches` 目录中已生成的简繁补丁数据，默认生成可直接运行的 `dist\FQ4ChinesePatch.exe`。

改动汉化内容或补丁逻辑后，用原版文件重新生成补丁数据，并将 `work\patcher` 中的 `patch_data.hpp`、`patch_data_cn.hpp`、`payload.bin` 和 `payload_cn.bin` 更新到 `patches`。

```bat
uv run --locked python .\tools\build_patcher.py --win "Windows 版目录" --dos "DOS 版目录"
```

## 使用

### 运行中文版游戏

构建完成后，进入所选版本的输出目录，双击 `fq4.exe`。

### 使用单文件补丁工具

从 [GitHub Releases](https://github.com/soarqin/fq4zh/releases) 下载并解压补丁包，或使用本地构建结果。双击 `FQ4ChinesePatch.exe`，通过「瀏覽…」选择 Windows 日文版 v1.10 的 `fq4.exe`。在左侧选择「繁體中文」或「简体中文」，补丁工具界面和游戏语言会一起切换。接着在底部选择一种补丁方式。

- 「產生中文版 EXE」或「生成中文版 EXE」在原版游戏目录生成可以双击启动的程序。繁体版文件名为 `fq4.zh.exe`，简体版为 `fq4.zh-CN.exe`。已有同名文件时，工具会复用内容相同的文件，或提示先重命名内容不同的文件。
- 「以記憶體補丁啟動」或「以内存补丁启动」立即启动游戏，汉化仅在本次运行中生效。游戏从原版目录读取资源和存档。

## 游戏手册

用浏览器打开对应的 HTML 手册，可离线查阅剧情、游戏操作和快捷键。[简体中文游戏手册](docs/FQ4-manual-zh-Hans.html) · [繁體中文遊戲手冊](docs/FQ4-manual-zh-Hant.html)

## 开发验证

截图和补丁验证脚本使用默认的 `dev` 依赖组。运行 `work\ida` 下的分析脚本时，需配置 IDA Pro，选择与其兼容的 Python 版本（3.10 或更新），并使用 `uv run --locked --group ida`。

## 发布

更新 `pyproject.toml` 中的版本号和 [变更日志](CHANGELOG.md)，运行 `uv lock` 后提交。推送对应的 `v主版本.次版本.修订号` 标签会触发 GitHub Actions，从仓库里的补丁数据编译 EXE，并发布包含补丁、简繁手册和项目说明的 ZIP。

需要补跑时，在 GitHub 的 Release 工作流中手动运行并选择已推送的标签。

## 许可

本项目的源代码采用 [MIT 许可证](LICENSE)。游戏、原版资源和游戏说明文档的相关权利归各自权利人所有。
