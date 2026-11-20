# First Queen IV Windows 版繁体中文移植

进入 `dist\FQ4`，双击 `fq4.exe`。移植版基于 Windows v1.10，游戏所需的资源已随产物复制。两个原版目录可继续独立使用。

剧情索引的 800 个槽位包含 787 条采用 DOS 官中的记录、12 条按 Windows 文本补译的记录，以及 1 个引擎用字表。人物、职业、国家、地图、道具和魔法共移植了 1,286 条有内容的记录。Windows 新增选单和「苦鬥」道具效果使用 DOS 版的既有术语补译。

## 单文件补丁工具

双击 [FQ4ChinesePatch.exe](dist/FQ4ChinesePatch.exe)，选择已验证的 Windows 日文版 v1.10 `fq4.exe`。补丁数据内置于工具，运行只使用 Windows 自带的 DLL。

- 「生成中文版 EXE」在游戏目录生成 `fq4.zh.exe`。之后可双击生成的文件进入中文版，日文版 `fq4.exe` 保留原名。
- 「以内存补丁启动」直接启动选中的日文版 EXE，在游戏初始化前应用汉化。补丁仅对本次启动生效，游戏仍在原目录读取资源和存档。

已有同名的中文版时，工具会校验并复用相同文件。如果内容不同，工具会提示先改名。两种模式应用补丁前都校验日文原版的 SHA-256。[实机验证记录](work/patcher/verification/result.json)

## 对照资料

| 文件 | 内容 |
| --- | --- |
| [work/catalog/dialogue.tsv](work/catalog/dialogue.tsv) | 两版剧情编号、文件偏移和原文 |
| [work/catalog/dos-ui.tsv](work/catalog/dos-ui.tsv) | DOS 界面文字及提取位置 |
| [work/build/dialogue.tsv](work/build/dialogue.tsv) | 剧情成稿、来源和 UTF-16 地址 |
| [work/build/terms.tsv](work/build/terms.tsv) | 两版名词、说明和最终译文 |
| [work/build/ui.tsv](work/build/ui.tsv) | 游戏内界面与程序提示的最终译文 |
| [work/build/ui-terms.tsv](work/build/ui-terms.tsv) | 界面用词及可匹配的 DOS 原文偏移 |

对照文件使用 UTF-8。来源为 `dos` 的剧情沿用官中文句，分页和选项按 Windows 界面排版。`dos-repaired` 对应第 18 槽，修复了官中文件中「讓」之前的损坏字节。`windows` 和 `windows-hard` 表示按 Windows 内容补译。

## 重建

`dist` 中的成品和 `work` 中的对照表、实测记录保存在本地。新检出的仓库可按下列命令重建成品与对照表。

工具使用 Python 3.9 或更新版本及 `pefile`。默认读取 `D:\Games\FQ4` 和 `D:\DOS\FQ4`，校验本次使用的三个源文件的 SHA-256。

```powershell
python -m pip install pefile
python .\tools\catalog.py
python .\tools\build.py
```

重新编译单文件补丁工具时，在 Visual Studio 的 x86 本机工具命令提示符中运行 `python .\tools\build_patcher.py`。构建会在 `work\patcher` 保存补丁数据和编译中间文件，在 `dist` 生成 `FQ4ChinesePatch.exe`。

剧情按编号从 UTF-16LE 区段读取，扩展索引后可容纳长于日文的译文。游戏原有的分页、立绘及界面控制码继续参与排版。菜单和数据表通过双字节字格保留固定布局，字格进入渲染时转换为 UTF-16，由 `DrawTextW` 绘制。游戏字体使用 Microsoft JhengHei UI，汉字沿用 16 像素字格。启动菜单和 Windows 提示也使用 Unicode。

本次移植覆盖程序文字。标题图、影片内嵌字样和随附的日文说明属于原版资源。

已在窗口模式实测启动、难度选择、开场对话和退出提示，并用第一格存档副本验证了读档及从世界地图选择「探索」进入地图。地图边框的短标签按双字节读取中文，再以 Unicode 绘制，保留原有字格和颜色。[部队名验证](work/labels/verification.json) · [运行记录](work/smoke-final/result.json) · [文件与字体校验](work/build/verification.json)

地图内状态栏的「姓名」每个成员占 32 像素，最多显示两个完整汉字。地图边框和人物选单可显示全名。辅助视窗的「待命中」直接使用 UTF-16 绘制。[绘字路径和验证记录](work/render-audit/verification.json)

## 音效特效兼容

在本机，原版第三个音效选项调用 DirectSound `SetFX` 加载 I3DL2 残响时返回 `0x80040154`，表示该组件类未注册。移植版遇到这个返回码时会尝试使用系统自带的 Waves Reverb，并按场景预设换算增益、衰减时间和高频衰减比例。两种残响都无法载入时，游戏会恢复 DirectMusic 音频通路。第二个选项使用普通 DirectSound 通路。

[音效验证记录](work/audio/verification.json) · [原版返回码](work/audio/original-fx.log) · [Waves 残响调用跟踪](work/audio/fixed-fx.log)
