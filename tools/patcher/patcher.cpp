#define UNICODE
#define _UNICODE
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <bcrypt.h>
#include <commctrl.h>
#include <commdlg.h>

#include <array>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include "resource.h"
#include "patcher_version.h"

#pragma comment(linker, "/manifestdependency:\"type='win32' name='Microsoft.Windows.Common-Controls' " \
    "version='6.0.0.0' processorArchitecture='*' publicKeyToken='6595b64144ccf1df' language='*'\"")

namespace {
namespace fs = std::filesystem;
using Bytes = std::vector<std::uint8_t>;

constexpr const wchar_t* tr(bool simplified, const wchar_t* zh_tw, const wchar_t* zh_cn) {
    return simplified ? zh_cn : zh_tw;
}

constexpr const wchar_t* title(bool simplified) {
    return tr(simplified, L"First Queen IV 中文補丁", L"First Queen IV 中文补丁");
}

struct PatchRecord {
    std::uint32_t file_offset, rva, size;
};

struct PatchData {
    std::uint32_t target_size, payload_size;
    std::uint32_t extension_rva, extension_size, code_rva, code_size;
    const std::array<std::uint8_t, 32>& target_hash;
    const PatchRecord *first, *last;

    const PatchRecord* begin() const { return first; }
    const PatchRecord* end() const { return last; }
};

#include "patch_data.hpp"
#include "patch_data_cn.hpp"

using zh_tw::kDiskOnly;
using zh_tw::kHeadersSize;
using zh_tw::kImageBase;
using zh_tw::kMessageBoxThunkOffset;
using zh_tw::kMessageBoxThunkRva;
using zh_tw::kSourceHash;
using zh_tw::kSourceSize;

struct PatchError {
    std::wstring traditional, simplified;
    std::optional<DWORD> code = std::nullopt;
};

[[noreturn]] void windows_error(const wchar_t* traditional, const wchar_t* simplified, DWORD code = GetLastError()) {
    throw PatchError{traditional, simplified, code};
}

class Handle {
public:
    explicit Handle(HANDLE handle) : handle_(handle) {}
    ~Handle() { close(); }
    Handle(const Handle&) = delete;
    Handle& operator=(const Handle&) = delete;

    explicit operator bool() const { return handle_ && handle_ != INVALID_HANDLE_VALUE; }
    HANDLE get() const { return handle_; }
    void close() {
        if (*this) {
            CloseHandle(handle_);
            handle_ = nullptr;
        }
    }

private:
    HANDLE handle_;
};

const std::uint8_t* patch_bytes(WORD resource_id, const PatchData& patch) {
    const auto resource = FindResourceW(nullptr, MAKEINTRESOURCEW(resource_id), RT_RCDATA);
    if (!resource || SizeofResource(nullptr, resource) != patch.payload_size)
        throw PatchError{L"內建補丁資源不完整。", L"内置补丁资源不完整。"};
    const auto loaded = LoadResource(nullptr, resource);
    const auto data = loaded ? LockResource(loaded) : nullptr;
    if (!data)
        throw PatchError{L"無法讀取內建補丁。", L"无法读取内置补丁。"};
    return static_cast<const std::uint8_t*>(data);
}

bool file_size_is(HANDLE file, std::uint32_t expected) {
    LARGE_INTEGER size{};
    if (!GetFileSizeEx(file, &size))
        windows_error(L"無法讀取 EXE 檔案大小", L"无法读取 EXE 文件大小");
    return size.QuadPart == expected;
}

Bytes read_file(HANDLE file, DWORD size) {
    Bytes data(size);
    DWORD count = 0;
    if (!ReadFile(file, data.data(), size, &count, nullptr))
        windows_error(L"無法讀取 EXE", L"无法读取 EXE");
    if (count != size)
        throw PatchError{L"EXE 檔案讀取不完整。", L"EXE 文件读取不完整。"};
    return data;
}

std::array<std::uint8_t, 32> sha256(const Bytes& data) {
    BCRYPT_ALG_HANDLE algorithm = nullptr;
    if (!BCRYPT_SUCCESS(BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0)))
        throw PatchError{L"無法初始化 SHA-256 驗證。", L"无法初始化 SHA-256 校验。"};
    std::array<std::uint8_t, 32> digest{};
    const auto status = BCryptHash(algorithm, nullptr, 0, const_cast<PUCHAR>(data.data()),
                                   static_cast<ULONG>(data.size()), digest.data(),
                                   static_cast<ULONG>(digest.size()));
    BCryptCloseAlgorithmProvider(algorithm, 0);
    if (!BCRYPT_SUCCESS(status))
        throw PatchError{L"無法完成 SHA-256 驗證。", L"无法完成 SHA-256 校验。"};
    return digest;
}

fs::path write_chinese_exe(fs::path source, Bytes image, const std::uint8_t* payload,
                           const PatchData& patch, const wchar_t* extension) {
    image.resize(patch.target_size);
    for (const auto& record : patch) {
        std::memcpy(image.data() + record.file_offset, payload, record.size);
        payload += record.size;
    }
    if (sha256(image) != patch.target_hash)
        throw PatchError{L"中文版 EXE 驗證失敗。", L"中文版 EXE 校验失败。"};

    const auto target = source.replace_extension(extension);
    {
        const Handle existing(CreateFileW(target.c_str(), GENERIC_READ, FILE_SHARE_READ,
                                         nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr));
        if (existing) {
            if (file_size_is(existing.get(), patch.target_size) &&
                sha256(read_file(existing.get(), patch.target_size)) == patch.target_hash)
                return target;
            const auto name = target.filename().wstring();
            throw PatchError{L"同目錄已有 " + name + L"。請重新命名後再產生。",
                             L"同目录已有 " + name + L"。请改名后再生成。"};
        }
        if (GetLastError() != ERROR_FILE_NOT_FOUND)
            windows_error(L"無法檢查中文版 EXE 的輸出路徑", L"无法检查中文版 EXE 的输出路径");
    }

    // Publish a complete file in a single rename, without replacing a file created concurrently.
    auto stage = target;
    stage += L"." + std::to_wstring(GetCurrentProcessId()) + L"." +
             std::to_wstring(GetTickCount64()) + L".tmp";
    Handle output(CreateFileW(stage.c_str(), GENERIC_WRITE, 0, nullptr,
                             CREATE_NEW, FILE_ATTRIBUTE_NORMAL, nullptr));
    if (!output)
        windows_error(L"無法在遊戲目錄建立中文版 EXE 的暫存檔", L"无法在游戏目录创建中文版 EXE 的临时文件");
    try {
        DWORD count = 0;
        if (!WriteFile(output.get(), image.data(), patch.target_size, &count, nullptr))
            windows_error(L"無法寫入中文版 EXE", L"无法写入中文版 EXE");
        if (count != patch.target_size)
            throw PatchError{L"中文版 EXE 寫入不完整。", L"中文版 EXE 写入不完整。"};
        if (!FlushFileBuffers(output.get()))
            windows_error(L"無法完成中文版 EXE 寫入", L"无法完成中文版 EXE 写入");
        output.close();
        if (!MoveFileExW(stage.c_str(), target.c_str(), MOVEFILE_WRITE_THROUGH))
            windows_error(L"無法儲存中文版 EXE", L"无法保存中文版 EXE");
    } catch (...) {
        output.close();
        DeleteFileW(stage.c_str());
        throw;
    }
    return target;
}

struct SuspendedGame {
    PROCESS_INFORMATION info{};
    bool started = false;
    ~SuspendedGame() {
        if (info.hProcess) {
            if (!started && TerminateProcess(info.hProcess, 1))
                WaitForSingleObject(info.hProcess, INFINITE);
            CloseHandle(info.hThread);
            CloseHandle(info.hProcess);
        }
    }
};

void* address(std::uint32_t rva) {
    return reinterpret_cast<void*>(static_cast<std::uintptr_t>(kImageBase) + rva);
}

void check_memory(HANDLE process, std::uint32_t rva, const std::uint8_t* expected, std::uint32_t size) {
    Bytes actual(size);
    SIZE_T count = 0;
    if (!ReadProcessMemory(process, address(rva), actual.data(), size, &count))
        windows_error(L"無法讀取遊戲的初始映像", L"无法读取游戏的初始映像");
    if (count != size || std::memcmp(actual.data(), expected, size) != 0)
        throw PatchError{L"啟動後的遊戲映像與已驗證的日文版 EXE 不一致。",
                         L"启动后的游戏映像与已校验的日文 EXE 不一致。"};
}

void write_memory(HANDLE process, const PatchRecord& record, const std::uint8_t* data,
                  std::uint32_t extension_rva) {
    // Original image sections may be read-only or executable. The new allocation
    // stays writable until all its bytes have been copied.
    const auto target = address(record.rva);
    const bool original_section = record.rva < extension_rva;
    DWORD previous = 0;
    if (original_section && !VirtualProtectEx(process, target, record.size, PAGE_READWRITE, &previous))
        windows_error(L"無法寫入遊戲的初始映像", L"无法写入游戏的初始映像");
    SIZE_T count = 0;
    if (!WriteProcessMemory(process, target, data, record.size, &count))
        windows_error(L"無法寫入記憶體補丁", L"无法写入内存补丁");
    if (count != record.size)
        throw PatchError{L"記憶體補丁寫入不完整。", L"内存补丁写入不完整。"};
    DWORD ignored = 0;
    if (original_section && !VirtualProtectEx(process, target, record.size, previous, &ignored))
        windows_error(L"無法還原遊戲映像的記憶體權限", L"无法恢复游戏映像的内存权限");
}

void launch_chinese(const fs::path& source, const Bytes& original, const std::uint8_t* payload,
                    const PatchData& patch) {
    SuspendedGame game;
    STARTUPINFOW startup{};
    startup.cb = sizeof(startup);
    const auto directory = source.parent_path();
    auto command = L"\"" + source.wstring() + L"\"";
    if (!CreateProcessW(source.c_str(), command.data(), nullptr, nullptr, FALSE, CREATE_SUSPENDED,
                        nullptr, directory.c_str(), &startup, &game.info))
        windows_error(L"無法啟動日文版遊戲 EXE", L"无法启动日文版游戏 EXE");

    const auto process = game.info.hProcess;
    MEMORY_BASIC_INFORMATION region{};
    if (!VirtualQueryEx(process, address(0), &region, sizeof(region)) ||
        region.Type != MEM_IMAGE || region.AllocationBase != address(0))
        throw PatchError{L"遊戲映像未載入至支援的位址。", L"游戏映像未加载到支持的地址。"};
    check_memory(process, 0, original.data(), kHeadersSize);
    // The imported MessageBoxW name must be patched before the loader binds the IAT.
    check_memory(process, kMessageBoxThunkRva, original.data() + kMessageBoxThunkOffset, sizeof(DWORD));

    const auto extension = VirtualAllocEx(process, address(patch.extension_rva), patch.extension_size,
                                         MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
    if (!extension)
        windows_error(L"無法為中文文字和繪字程式碼配置記憶體", L"无法为中文文本和绘字代码分配内存");
    if (extension != address(patch.extension_rva))
        throw PatchError{L"中文化資料未載入至遊戲使用的位址。", L"汉化数据未加载到游戏使用的地址。"};

    for (const auto& record : patch) {
        if (record.rva != kDiskOnly) {
            if (record.rva < patch.extension_rva)
                check_memory(process, record.rva, original.data() + record.file_offset, record.size);
            write_memory(process, record, payload, patch.extension_rva);
        }
        payload += record.size;
    }
    DWORD ignored = 0;
    if (!VirtualProtectEx(process, extension, patch.extension_size, PAGE_READONLY, &ignored) ||
        !VirtualProtectEx(process, address(patch.code_rva), patch.code_size, PAGE_EXECUTE_READ, &ignored))
        windows_error(L"無法設定中文化資料的記憶體權限", L"无法设置汉化数据的内存权限");
    if (!FlushInstructionCache(process, nullptr, 0))
        windows_error(L"無法重新整理遊戲的指令快取", L"无法刷新游戏的指令缓存");

    AllowSetForegroundWindow(game.info.dwProcessId);
    const DWORD suspend_count = ResumeThread(game.info.hThread);
    if (suspend_count == static_cast<DWORD>(-1))
        windows_error(L"無法繼續執行遊戲程序", L"无法恢复游戏进程");
    if (suspend_count != 1)
        throw PatchError{L"遊戲主執行緒的狀態異常。", L"游戏主线程的状态异常。"};
    game.started = true;
}

// Dialog units match the controls in patcher.rc.
constexpr RECT kSourceFrame{118, 60, 382, 77};
constexpr COLORREF kCanvas = RGB(24, 31, 37);
constexpr COLORREF kPanel = RGB(35, 44, 51);
constexpr COLORREF kRule = RGB(74, 88, 92);
constexpr COLORREF kHighlight = RGB(49, 66, 70);
constexpr COLORREF kInk = RGB(236, 231, 211);
constexpr COLORREF kMuted = RGB(174, 187, 180);
constexpr COLORREF kGold = RGB(238, 195, 118);
constexpr COLORREF kMint = RGB(128, 199, 169);

struct DialogStyle {
    HFONT heading_font = nullptr;
    HFONT body_font = nullptr;
    bool high_contrast = false;
    bool success = false;
};

void update_contrast(HWND dialog, DialogStyle& style) {
    HIGHCONTRASTW contrast{};
    contrast.cbSize = sizeof(contrast);
    if (!SystemParametersInfoW(SPI_GETHIGHCONTRAST, sizeof(contrast), &contrast, 0))
        return;
    const bool enabled = (contrast.dwFlags & HCF_HIGHCONTRASTON) != 0;
    if (enabled == style.high_contrast)
        return;
    style.high_contrast = enabled;
    const auto edit = GetDlgItem(dialog, IDC_SOURCE);
    const auto flags = GetWindowLongW(edit, GWL_STYLE);
    SetWindowLongW(edit, GWL_STYLE, enabled ? flags | WS_BORDER : flags & ~WS_BORDER);
    SetWindowPos(edit, nullptr, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED);
    RedrawWindow(dialog, nullptr, nullptr, RDW_INVALIDATE | RDW_ERASE | RDW_ALLCHILDREN);
}

BOOL CALLBACK set_body_font(HWND control, LPARAM font) {
    SendMessageW(control, WM_SETFONT, static_cast<WPARAM>(font), FALSE);
    return TRUE;
}

void set_fonts(HWND dialog, DialogStyle& style) {
    const auto font = reinterpret_cast<HFONT>(SendMessageW(dialog, WM_GETFONT, 0, 0));
    LOGFONTW metrics{};
    if (!font || !GetObjectW(font, sizeof(metrics), &metrics))
        return;
    const auto height = metrics.lfHeight;
    metrics.lfHeight = MulDiv(height, 5, 4);
    style.body_font = CreateFontIndirectW(&metrics);
    if (style.body_font)
        EnumChildWindows(dialog, set_body_font, reinterpret_cast<LPARAM>(style.body_font));
    metrics.lfHeight = MulDiv(height, 7, 3);
    metrics.lfWeight = FW_BOLD;
    style.heading_font = CreateFontIndirectW(&metrics);
    if (style.heading_font)
        SendDlgItemMessageW(dialog, IDC_HEADING, WM_SETFONT, reinterpret_cast<WPARAM>(style.heading_font), FALSE);
}

RECT pixels(HWND dialog, RECT units) {
    MapDialogRect(dialog, &units);
    return units;
}

HBRUSH brush(HDC dc, COLORREF color) {
    SetDCBrushColor(dc, color);
    return static_cast<HBRUSH>(GetStockObject(DC_BRUSH));
}

void fill(HDC dc, const RECT& area, COLORREF color) {
    FillRect(dc, &area, brush(dc, color));
}

void draw_background(HWND dialog, HDC dc) {
    RECT client{};
    GetClientRect(dialog, &client);
    fill(dc, client, kCanvas);
    fill(dc, pixels(dialog, {12, 34, 444, 35}), kRule);
    fill(dc, pixels(dialog, {108, 43, 109, 166}), kPanel);
    fill(dc, pixels(dialog, {118, 103, 444, 120}), kPanel);
    fill(dc, pixels(dialog, {118, 123, 444, 140}), kPanel);
    fill(dc, pixels(dialog, {12, 174, 444, 175}), kRule);

    auto field = pixels(dialog, kSourceFrame);
    const bool focused = GetFocus() == GetDlgItem(dialog, IDC_SOURCE);
    fill(dc, field, focused ? kGold : kRule);
    InflateRect(&field, -1, -1);
    fill(dc, field, kPanel);
}

void draw_button(HWND dialog, const NMCUSTOMDRAW& item) {
    const auto id = static_cast<int>(item.hdr.idFrom);
    const bool language = id == IDC_TRADITIONAL || id == IDC_SIMPLIFIED;
    const bool active = language && IsDlgButtonChecked(dialog, id) == BST_CHECKED;
    const bool focused = GetFocus() == item.hdr.hwndFrom;
    const bool pressed = (item.uItemState & CDIS_SELECTED) != 0;
    const bool hot = (item.uItemState & CDIS_HOT) != 0;
    auto background = language ? kCanvas : kPanel;
    if (active || focused || pressed || hot)
        background = kHighlight;
    if (id == IDC_LAUNCH)
        background = pressed ? RGB(106, 180, 150) : hot ? RGB(151, 214, 189) : kMint;
    fill(item.hdc, item.rc, background);

    const auto marker = pixels(dialog, {0, 0, 2, 1});
    if (language && (active || focused)) {
        auto mark = item.rc;
        mark.right = mark.left + marker.right;
        fill(item.hdc, mark, focused ? kGold : kMint);
    } else if (focused) {
        auto mark = item.rc;
        mark.top = mark.bottom - marker.bottom;
        fill(item.hdc, mark, kGold);
    }

    wchar_t label[64]{};
    GetWindowTextW(item.hdr.hwndFrom, label, ARRAYSIZE(label));
    const auto padding = pixels(dialog, {0, 0, 8, 0}).right;
    auto area = item.rc;
    area.left += padding;
    area.right -= padding;
    SetBkMode(item.hdc, TRANSPARENT);
    SetTextColor(item.hdc, id == IDC_LAUNCH ? kCanvas : language && !active && !focused ? kMuted : kInk);
    const auto font = reinterpret_cast<HFONT>(SendMessageW(item.hdr.hwndFrom, WM_GETFONT, 0, 0));
    const auto previous = font ? SelectObject(item.hdc, font) : nullptr;
    DrawTextW(item.hdc, label, -1, &area, DT_SINGLELINE | DT_VCENTER | DT_NOPREFIX |
                                          (id == IDC_BROWSE ? DT_CENTER : DT_LEFT));
    if (previous)
        SelectObject(item.hdc, previous);
}

INT_PTR control_colors(HDC dc, int id, bool success) {
    auto foreground = kInk;
    auto background = kCanvas;
    switch (id) {
    case IDC_LANGUAGE_LABEL:
    case IDC_SOURCE_LABEL:
    case IDC_MODE_LABEL:
        foreground = kGold;
        break;
    case IDC_VERSION:
        foreground = kMuted;
        break;
    case IDC_STATUS:
        foreground = success ? kMint : kMuted;
        break;
    case IDC_MEMORY_DETAIL:
    case IDC_DISK_DETAIL:
        foreground = kMuted;
        [[fallthrough]];
    case IDC_SOURCE:
    case IDC_MEMORY_LABEL:
    case IDC_DISK_LABEL:
        background = kPanel;
        break;
    }
    SetBkColor(dc, background);
    SetTextColor(dc, foreground);
    return reinterpret_cast<INT_PTR>(brush(dc, background));
}

void set_status(HWND dialog, const wchar_t* text, bool success = false) {
    auto* style = reinterpret_cast<DialogStyle*>(GetWindowLongPtrW(dialog, DWLP_USER));
    style->success = success;
    SetDlgItemTextW(dialog, IDC_STATUS, text);
}

bool simplified_selected(HWND dialog) {
    return IsDlgButtonChecked(dialog, IDC_SIMPLIFIED) == BST_CHECKED;
}

const wchar_t* output_extension(bool simplified) {
    return simplified ? L".zh-CN.exe" : L".zh.exe";
}

void reset_status(HWND dialog) {
    set_status(dialog, tr(simplified_selected(dialog), L"支援 Windows 日文版 v1.10 的原始 EXE。",
                                                      L"支持 Windows 日文版 v1.10 的原始 EXE。"));
}

void update_language(HWND dialog) {
    const bool simplified = simplified_selected(dialog);
    SetWindowTextW(dialog, tr(simplified, L"First Queen IV 中文補丁 v" FQ4_VERSION,
                                         L"First Queen IV 中文补丁 v" FQ4_VERSION));

    static constexpr struct {
        int id;
        const wchar_t* traditional;
        const wchar_t* simplified;
    } labels[] = {
        {IDC_HEADING, L"啟動設定", L"启动设置"},
        {IDC_LANGUAGE_LABEL, L"遊戲語言", L"游戏语言"},
        {IDC_SOURCE_LABEL, L"日文版遊戲 EXE", L"日文版游戏 EXE"},
        {IDC_BROWSE, L"瀏覽…", L"浏览…"},
        {IDC_MODE_LABEL, L"補丁方式", L"补丁方式"},
        {IDC_MEMORY_LABEL, L"記憶體補丁", L"内存补丁"},
        {IDC_MEMORY_DETAIL, L"僅在本次執行時生效", L"仅本次运行生效"},
        {IDC_DISK_LABEL, L"產生檔案", L"生成文件"},
        {IDC_LAUNCH, L"以記憶體補丁啟動", L"以内存补丁启动"},
        {IDC_WRITE, L"產生中文版 EXE", L"生成中文版 EXE"},
        {IDCANCEL, L"離開", L"退出"},
    };
    for (const auto& label : labels)
        SetDlgItemTextW(dialog, label.id, tr(simplified, label.traditional, label.simplified));

    const auto detail = tr(simplified, L"儲存至遊戲目錄（", L"保存到游戏目录（") +
                        std::wstring(output_extension(simplified)) + L"）";
    SetDlgItemTextW(dialog, IDC_DISK_DETAIL, detail.c_str());
    reset_status(dialog);
}

void show_error(HWND dialog, const PatchError& error) {
    const bool simplified = simplified_selected(dialog);
    auto message = simplified ? error.simplified : error.traditional;
    if (error.code) {
        const auto lang = MAKELANGID(LANG_CHINESE, simplified ? SUBLANG_CHINESE_SIMPLIFIED :
                                                                SUBLANG_CHINESE_TRADITIONAL);
        wchar_t details[512]{};
        constexpr DWORD flags = FORMAT_MESSAGE_FROM_SYSTEM | FORMAT_MESSAGE_IGNORE_INSERTS;
        DWORD length = FormatMessageW(flags, nullptr, *error.code, lang, details, ARRAYSIZE(details), nullptr);
        if (!length)
            length = FormatMessageW(flags, nullptr, *error.code, 0, details, ARRAYSIZE(details), nullptr);
        message += tr(simplified, L"（Windows 錯誤 ", L"（Windows 错误 ") + std::to_wstring(*error.code) + L"）";
        if (length)
            message += L"\n" + std::wstring(details, length);
    }
    MessageBoxW(dialog, message.c_str(), title(simplified), MB_OK | MB_ICONERROR);
}

void browse(HWND dialog) {
    const bool simplified = simplified_selected(dialog);
    std::array<wchar_t, 32768> filename{};
    OPENFILENAMEW options{};
    options.lStructSize = sizeof(options);
    options.hwndOwner = dialog;
    options.lpstrFilter = tr(simplified, L"遊戲程式 (*.exe)\0*.exe\0", L"游戏程序 (*.exe)\0*.exe\0");
    options.lpstrFile = filename.data();
    options.nMaxFile = static_cast<DWORD>(filename.size());
    options.lpstrTitle = tr(simplified, L"選擇日文版 First Queen IV", L"选择日文版 First Queen IV");
    options.Flags = OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST | OFN_NOCHANGEDIR;
    if (GetOpenFileNameW(&options))
        SetDlgItemTextW(dialog, IDC_SOURCE, filename.data());
    else if (CommDlgExtendedError())
        throw PatchError{L"無法開啟檔案選擇視窗。", L"无法打开文件选择窗口。"};
}

fs::path selected_path(HWND dialog) {
    const int length = GetWindowTextLengthW(GetDlgItem(dialog, IDC_SOURCE));
    if (length == 0)
        throw PatchError{L"請選擇日文版遊戲 EXE。", L"请选择日文版游戏 EXE。"};
    std::wstring path(static_cast<std::size_t>(length) + 1, L'\0');
    path.resize(GetDlgItemTextW(dialog, IDC_SOURCE, path.data(), length + 1));
    if (path.size() >= 2 && path.front() == L'"' && path.back() == L'"')
        path = path.substr(1, path.size() - 2);
    return fs::absolute(path).lexically_normal();
}

void apply(HWND dialog, bool launch) {
    const auto source = selected_path(dialog);
    // Hold the checked EXE open while creating the process from that path.
    const Handle file(CreateFileW(source.c_str(), GENERIC_READ, FILE_SHARE_READ,
                                  nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr));
    if (!file)
        windows_error(L"無法開啟日文版遊戲 EXE", L"无法打开日文版游戏 EXE");
    constexpr auto unsupported_tw = L"請選擇 Windows 日文版 v1.10 的原始 EXE。";
    constexpr auto unsupported_cn = L"请选择 Windows 日文版 v1.10 的原始 EXE。";
    if (!file_size_is(file.get(), kSourceSize))
        throw PatchError{unsupported_tw, unsupported_cn};
    auto original = read_file(file.get(), kSourceSize);
    if (sha256(original) != kSourceHash)
        throw PatchError{unsupported_tw, unsupported_cn};
    const bool simplified = simplified_selected(dialog);
    const auto& patch = simplified ? zh_cn::kPatch : zh_tw::kPatch;
    const auto payload = patch_bytes(simplified ? IDR_PAYLOAD_CN : IDR_PAYLOAD, patch);
    if (launch) {
        launch_chinese(source, original, payload, patch);
        set_status(dialog, tr(simplified, L"中文版已啟動。本次啟動使用記憶體補丁。",
                                          L"中文版已启动。本次启动使用内存补丁。"), true);
    } else {
        const auto target = write_chinese_exe(source, std::move(original), payload, patch, output_extension(simplified));
        const auto status = tr(simplified, L"中文版 EXE 已就緒。 ", L"中文版 EXE 已就绪。 ") +
                            target.filename().wstring();
        set_status(dialog, status.c_str(), true);
    }
}

INT_PTR CALLBACK dialog_proc(HWND dialog, UINT message, WPARAM param, LPARAM data) {
    try {
        if (message == WM_INITDIALOG) {
            auto& style = *reinterpret_cast<DialogStyle*>(data);
            SetWindowLongPtrW(dialog, DWLP_USER, data);
            set_fonts(dialog, style);
            update_contrast(dialog, style);
            CheckRadioButton(dialog, IDC_TRADITIONAL, IDC_SIMPLIFIED, IDC_TRADITIONAL);
            update_language(dialog);
            std::array<wchar_t, 32768> path{};
            const auto length = GetModuleFileNameW(nullptr, path.data(), static_cast<DWORD>(path.size()));
            if (length > 0 && length < path.size()) {
                const auto adjacent = fs::path(path.data()).parent_path() / L"fq4.exe";
                std::error_code error;
                if (fs::is_regular_file(adjacent, error))
                    SetDlgItemTextW(dialog, IDC_SOURCE, adjacent.c_str());
            }
            return TRUE;
        }
        auto* style = reinterpret_cast<DialogStyle*>(GetWindowLongPtrW(dialog, DWLP_USER));
        if (style && (message == WM_SETTINGCHANGE || message == WM_SYSCOLORCHANGE))
            update_contrast(dialog, *style);
        if (style && !style->high_contrast) {
            switch (message) {
            case WM_ERASEBKGND:
                draw_background(dialog, reinterpret_cast<HDC>(param));
                return TRUE;
            case WM_CTLCOLOREDIT:
            case WM_CTLCOLORSTATIC:
                return control_colors(reinterpret_cast<HDC>(param), GetDlgCtrlID(reinterpret_cast<HWND>(data)),
                                      style->success);
            case WM_NOTIFY: {
                const auto* header = reinterpret_cast<const NMHDR*>(data);
                if (header->code == NM_CUSTOMDRAW) {
                    const auto& item = *reinterpret_cast<const NMCUSTOMDRAW*>(data);
                    if (item.dwDrawStage == CDDS_PREPAINT) {
                        draw_button(dialog, item);
                        SetWindowLongPtrW(dialog, DWLP_MSGRESULT, CDRF_SKIPDEFAULT);
                        return TRUE;
                    }
                }
                break;
            }
            }
        }
        if (message == WM_COMMAND) {
            const auto notification = HIWORD(param);
            if (LOWORD(param) == IDC_SOURCE && style) {
                if (notification == EN_CHANGE) {
                    reset_status(dialog);
                    return TRUE;
                }
                if (!style->high_contrast && (notification == EN_SETFOCUS || notification == EN_KILLFOCUS)) {
                    const auto field = pixels(dialog, kSourceFrame);
                    InvalidateRect(dialog, &field, TRUE);
                }
            }
            if (notification != BN_CLICKED)
                return FALSE;
            switch (LOWORD(param)) {
            case IDC_TRADITIONAL:
            case IDC_SIMPLIFIED:
                update_language(dialog);
                return TRUE;
            case IDC_BROWSE:
                browse(dialog);
                return TRUE;
            case IDC_WRITE:
            case IDC_LAUNCH:
                reset_status(dialog);
                apply(dialog, LOWORD(param) == IDC_LAUNCH);
                return TRUE;
            case IDCANCEL:
                EndDialog(dialog, 0);
                return TRUE;
            }
        }
    } catch (const PatchError& error) {
        show_error(dialog, error);
        return TRUE;
    } catch (const std::exception&) {
        const bool simplified = simplified_selected(dialog);
        MessageBoxW(dialog, tr(simplified, L"無法處理所選的遊戲路徑或檔案。", L"无法处理选中的游戏路径或文件。"),
                    title(simplified), MB_OK | MB_ICONERROR);
        return TRUE;
    }
    return FALSE;
}
}  // namespace

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE, PWSTR, int) {
    SetProcessDPIAware();
    DialogStyle style;
    const auto result = DialogBoxParamW(instance, MAKEINTRESOURCEW(IDD_PATCHER), nullptr, dialog_proc,
                                        reinterpret_cast<LPARAM>(&style));
    if (style.heading_font)
        DeleteObject(style.heading_font);
    if (style.body_font)
        DeleteObject(style.body_font);
    if (result == -1) {
        MessageBoxW(nullptr, L"無法開啟補丁工具視窗。", title(false), MB_OK | MB_ICONERROR);
        return 1;
    }
    return 0;
}
