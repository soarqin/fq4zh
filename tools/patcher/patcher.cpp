#define UNICODE
#define _UNICODE
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <bcrypt.h>
#include <commdlg.h>

#include <array>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <string>
#include <utility>
#include <vector>

#include "resource.h"

#pragma comment(linker, "/manifestdependency:\"type='win32' name='Microsoft.Windows.Common-Controls' " \
    "version='6.0.0.0' processorArchitecture='*' publicKeyToken='6595b64144ccf1df' language='*'\"")

namespace {
namespace fs = std::filesystem;
using Bytes = std::vector<std::uint8_t>;
constexpr auto kTitle = L"First Queen IV 中文补丁";
constexpr auto kVersionHint = L"支持此次校验的 Windows 日文版 v1.10。";

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
    std::wstring message;
};

[[noreturn]] void windows_error(const wchar_t* step, DWORD code = GetLastError()) {
    wchar_t details[512]{};
    FormatMessageW(FORMAT_MESSAGE_FROM_SYSTEM | FORMAT_MESSAGE_IGNORE_INSERTS,
                   nullptr, code, 0, details, ARRAYSIZE(details), nullptr);
    throw PatchError{std::wstring(step) + L"（Windows 错误 " + std::to_wstring(code) + L"）\n" + details};
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
        throw PatchError{L"内置补丁资源不完整。"};
    const auto loaded = LoadResource(nullptr, resource);
    const auto data = loaded ? LockResource(loaded) : nullptr;
    if (!data)
        throw PatchError{L"无法读取内置补丁。"};
    return static_cast<const std::uint8_t*>(data);
}

bool file_size_is(HANDLE file, std::uint32_t expected) {
    LARGE_INTEGER size{};
    if (!GetFileSizeEx(file, &size))
        windows_error(L"无法读取 EXE 文件大小");
    return size.QuadPart == expected;
}

Bytes read_file(HANDLE file, DWORD size) {
    Bytes data(size);
    DWORD count = 0;
    if (!ReadFile(file, data.data(), size, &count, nullptr))
        windows_error(L"无法读取 EXE");
    if (count != size)
        throw PatchError{L"EXE 文件读取不完整。"};
    return data;
}

std::array<std::uint8_t, 32> sha256(const Bytes& data) {
    BCRYPT_ALG_HANDLE algorithm = nullptr;
    if (!BCRYPT_SUCCESS(BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0)))
        throw PatchError{L"无法初始化 SHA-256 校验。"};
    std::array<std::uint8_t, 32> digest{};
    const auto status = BCryptHash(algorithm, nullptr, 0, const_cast<PUCHAR>(data.data()),
                                   static_cast<ULONG>(data.size()), digest.data(),
                                   static_cast<ULONG>(digest.size()));
    BCryptCloseAlgorithmProvider(algorithm, 0);
    if (!BCRYPT_SUCCESS(status))
        throw PatchError{L"无法完成 SHA-256 校验。"};
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
        throw PatchError{L"中文版 EXE 校验失败。"};

    const auto target = source.replace_extension(extension);
    {
        const Handle existing(CreateFileW(target.c_str(), GENERIC_READ, FILE_SHARE_READ,
                                         nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr));
        if (existing) {
            if (file_size_is(existing.get(), patch.target_size) &&
                sha256(read_file(existing.get(), patch.target_size)) == patch.target_hash)
                return target;
            throw PatchError{L"同目录已有 " + target.filename().wstring() + L"。请改名后再生成。"};
        }
        if (GetLastError() != ERROR_FILE_NOT_FOUND)
            windows_error(L"无法检查中文版 EXE 的输出路径");
    }

    // Publish a complete file in a single rename, without replacing a file created concurrently.
    auto stage = target;
    stage += L"." + std::to_wstring(GetCurrentProcessId()) + L"." +
             std::to_wstring(GetTickCount64()) + L".tmp";
    Handle output(CreateFileW(stage.c_str(), GENERIC_WRITE, 0, nullptr,
                             CREATE_NEW, FILE_ATTRIBUTE_NORMAL, nullptr));
    if (!output)
        windows_error(L"无法在游戏目录创建中文版 EXE 的临时文件");
    try {
        DWORD count = 0;
        if (!WriteFile(output.get(), image.data(), patch.target_size, &count, nullptr))
            windows_error(L"无法写入中文版 EXE");
        if (count != patch.target_size)
            throw PatchError{L"中文版 EXE 写入不完整。"};
        if (!FlushFileBuffers(output.get()))
            windows_error(L"无法完成中文版 EXE 写入");
        output.close();
        if (!MoveFileExW(stage.c_str(), target.c_str(), MOVEFILE_WRITE_THROUGH))
            windows_error(L"无法保存中文版 EXE");
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
        windows_error(L"无法读取游戏的初始映像");
    if (count != size || std::memcmp(actual.data(), expected, size) != 0)
        throw PatchError{L"启动后的游戏映像与已校验的日文 EXE 不一致。"};
}

void write_memory(HANDLE process, const PatchRecord& record, const std::uint8_t* data,
                  std::uint32_t extension_rva) {
    // Original image sections may be read-only or executable. The new allocation
    // stays writable until all its bytes have been copied.
    const auto target = address(record.rva);
    const bool original_section = record.rva < extension_rva;
    DWORD previous = 0;
    if (original_section && !VirtualProtectEx(process, target, record.size, PAGE_READWRITE, &previous))
        windows_error(L"无法写入游戏的初始映像");
    SIZE_T count = 0;
    if (!WriteProcessMemory(process, target, data, record.size, &count))
        windows_error(L"无法写入内存补丁");
    if (count != record.size)
        throw PatchError{L"内存补丁写入不完整。"};
    DWORD ignored = 0;
    if (original_section && !VirtualProtectEx(process, target, record.size, previous, &ignored))
        windows_error(L"无法恢复游戏映像的内存权限");
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
        windows_error(L"无法启动日文版游戏 EXE");

    const auto process = game.info.hProcess;
    MEMORY_BASIC_INFORMATION region{};
    if (!VirtualQueryEx(process, address(0), &region, sizeof(region)) ||
        region.Type != MEM_IMAGE || region.AllocationBase != address(0))
        throw PatchError{L"游戏映像未加载到支持的地址。"};
    check_memory(process, 0, original.data(), kHeadersSize);
    // The imported MessageBoxW name must be patched before the loader binds the IAT.
    check_memory(process, kMessageBoxThunkRva, original.data() + kMessageBoxThunkOffset, sizeof(DWORD));

    const auto extension = VirtualAllocEx(process, address(patch.extension_rva), patch.extension_size,
                                         MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
    if (!extension)
        windows_error(L"无法为中文文本和绘字代码分配内存");
    if (extension != address(patch.extension_rva))
        throw PatchError{L"汉化数据未加载到游戏使用的地址。"};

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
        windows_error(L"无法设置汉化数据的内存权限");
    if (!FlushInstructionCache(process, nullptr, 0))
        windows_error(L"无法刷新游戏的指令缓存");

    AllowSetForegroundWindow(game.info.dwProcessId);
    const DWORD suspend_count = ResumeThread(game.info.hThread);
    if (suspend_count == static_cast<DWORD>(-1))
        windows_error(L"无法恢复游戏进程");
    if (suspend_count != 1)
        throw PatchError{L"游戏主线程的状态异常。"};
    game.started = true;
}

void browse(HWND dialog) {
    std::array<wchar_t, 32768> filename{};
    OPENFILENAMEW options{};
    options.lStructSize = sizeof(options);
    options.hwndOwner = dialog;
    options.lpstrFilter = L"游戏程序 (*.exe)\0*.exe\0";
    options.lpstrFile = filename.data();
    options.nMaxFile = static_cast<DWORD>(filename.size());
    options.lpstrTitle = L"选择日文版 First Queen IV";
    options.Flags = OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST | OFN_NOCHANGEDIR;
    if (GetOpenFileNameW(&options))
        SetDlgItemTextW(dialog, IDC_SOURCE, filename.data());
    else if (CommDlgExtendedError())
        throw PatchError{L"无法打开文件选择窗口。"};
}

fs::path selected_path(HWND dialog) {
    const int length = GetWindowTextLengthW(GetDlgItem(dialog, IDC_SOURCE));
    if (length == 0)
        throw PatchError{L"请选择日文版游戏 EXE。"};
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
        windows_error(L"无法打开日文版游戏 EXE");
    const auto unsupported = L"请选择此次校验的 Windows 日文版 v1.10 原始 EXE。";
    if (!file_size_is(file.get(), kSourceSize))
        throw PatchError{unsupported};
    auto original = read_file(file.get(), kSourceSize);
    if (sha256(original) != kSourceHash)
        throw PatchError{unsupported};
    const bool simplified = IsDlgButtonChecked(dialog, IDC_SIMPLIFIED) == BST_CHECKED;
    const auto& patch = simplified ? zh_cn::kPatch : zh_tw::kPatch;
    const auto payload = patch_bytes(simplified ? IDR_PAYLOAD_CN : IDR_PAYLOAD, patch);
    if (launch) {
        launch_chinese(source, original, payload, patch);
        SetDlgItemTextW(dialog, IDC_STATUS, L"中文版已启动。本次启动使用内存补丁。");
    } else {
        const auto target = write_chinese_exe(source, std::move(original), payload, patch,
                                              simplified ? L".zh-CN.exe" : L".zh.exe");
        const auto status = L"同目录的 " + target.filename().wstring() + L" 已就绪。";
        SetDlgItemTextW(dialog, IDC_STATUS, status.c_str());
    }
}

INT_PTR CALLBACK dialog_proc(HWND dialog, UINT message, WPARAM param, LPARAM) {
    try {
        if (message == WM_INITDIALOG) {
            CheckRadioButton(dialog, IDC_TRADITIONAL, IDC_SIMPLIFIED, IDC_TRADITIONAL);
            SetDlgItemTextW(dialog, IDC_STATUS, kVersionHint);
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
        if (message == WM_COMMAND) {
            const auto notification = HIWORD(param);
            if (LOWORD(param) == IDC_SOURCE && notification == EN_CHANGE) {
                SetDlgItemTextW(dialog, IDC_STATUS, kVersionHint);
                return TRUE;
            }
            if (notification != BN_CLICKED)
                return FALSE;
            switch (LOWORD(param)) {
            case IDC_TRADITIONAL:
            case IDC_SIMPLIFIED:
                SetDlgItemTextW(dialog, IDC_STATUS, kVersionHint);
                return TRUE;
            case IDC_BROWSE:
                browse(dialog);
                return TRUE;
            case IDC_WRITE:
            case IDC_LAUNCH:
                SetDlgItemTextW(dialog, IDC_STATUS, kVersionHint);
                apply(dialog, LOWORD(param) == IDC_LAUNCH);
                return TRUE;
            case IDCANCEL:
                EndDialog(dialog, 0);
                return TRUE;
            }
        }
    } catch (const PatchError& error) {
        MessageBoxW(dialog, error.message.c_str(), kTitle, MB_OK | MB_ICONERROR);
        return TRUE;
    } catch (const std::exception&) {
        MessageBoxW(dialog, L"无法处理选中的游戏路径或文件。", kTitle, MB_OK | MB_ICONERROR);
        return TRUE;
    }
    return FALSE;
}
}  // namespace

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE, PWSTR, int) {
    SetProcessDPIAware();
    if (DialogBoxParamW(instance, MAKEINTRESOURCEW(IDD_PATCHER), nullptr, dialog_proc, 0) == -1) {
        MessageBoxW(nullptr, L"无法打开补丁工具窗口。", kTitle, MB_OK | MB_ICONERROR);
        return 1;
    }
    return 0;
}
