# Changelog

本文件记录项目各版本的主要改动。格式参照 [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)，版本号遵循 [Semantic Versioning](https://semver.org/spec/v2.0.0.html)。

## [Unreleased]

### Fixed

- 修复简体版大地图「部队移动」和阵型菜单「一列阵型」中残留的繁体字。

## [1.0.2] - 2026-11-25

### Changed

- 切换左侧的简繁选项时，补丁工具的标题、按钮、状态和错误提示也会立即切换语言。

### Fixed

- 补译援军名单标题、势力图国家名、骑马菜单、战场消息、系统提示和两处地图事件，补齐部分简体界面术语。

## [1.0.1] - 2026-11-23

### Changed

- 重做单文件补丁工具界面，新增深色布局和简繁语言侧栏，并显示所选语言的输出文件后缀。

### Fixed

- 修复在大地图点击据点后，弹窗中的部队名缺字或乱码的问题。
- 修复移动确认、部队名单和战斗信息中的中文人名、部队名与兵种名乱码。
- 修复选择「开启音效与特效」后游戏音效无法正常播放的问题。

## [1.0.0] - 2026-11-21

### Added

- 将 DOS 版官方繁体文本移植到 Windows 日文版 v1.10，并提供使用大陆常用术语的简体版。
- 提供单文件补丁工具，可切换简繁语言、生成中文版 EXE 或以内存补丁启动游戏。
- 提供简体和繁体的离线 HTML 游戏手册。
- 补丁工具标题显示版本号，GitHub Actions 在推送版本标签后构建并发布补丁包。
- 项目源代码采用 MIT 许可。

### Changed

- 使用 uv 和锁文件管理 Python 构建依赖。
- 游戏内简体使用黑体，繁体使用微软正黑体，并按原版字格调整字形比例。

### Fixed

- 修复地图部队名、状态栏等位置的中文显示问题，并校正繁体文字的垂直位置。
- 为音效特效初始化提供兼容性回退。

[Unreleased]: https://github.com/soarqin/fq4zh/compare/v1.0.2...HEAD
[1.0.2]: https://github.com/soarqin/fq4zh/releases/tag/v1.0.2
[1.0.1]: https://github.com/soarqin/fq4zh/releases/tag/v1.0.1
[1.0.0]: https://github.com/soarqin/fq4zh/releases/tag/v1.0.0
