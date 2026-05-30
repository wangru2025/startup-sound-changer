from __future__ import annotations

import ctypes
from ctypes import wintypes
from pathlib import Path


kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LOAD_LIBRARY_AS_DATAFILE = 0x00000002
DONT_RESOLVE_DLL_REFERENCES = 0x00000001

kernel32.LoadLibraryExW.argtypes = [wintypes.LPCWSTR, wintypes.HANDLE, wintypes.DWORD]
kernel32.LoadLibraryExW.restype = wintypes.HANDLE

kernel32.FindResourceExW.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.WORD]
kernel32.FindResourceExW.restype = wintypes.HANDLE

kernel32.LoadResource.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
kernel32.LoadResource.restype = wintypes.HANDLE

kernel32.SizeofResource.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
kernel32.SizeofResource.restype = wintypes.DWORD

kernel32.LockResource.argtypes = [wintypes.HANDLE]
kernel32.LockResource.restype = wintypes.LPVOID

kernel32.FreeLibrary.argtypes = [wintypes.HANDLE]
kernel32.FreeLibrary.restype = wintypes.BOOL

kernel32.BeginUpdateResourceW.argtypes = [wintypes.LPCWSTR, wintypes.BOOL]
kernel32.BeginUpdateResourceW.restype = wintypes.HANDLE

kernel32.UpdateResourceW.argtypes = [
    wintypes.HANDLE,
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    wintypes.WORD,
    wintypes.LPVOID,
    wintypes.DWORD,
]
kernel32.UpdateResourceW.restype = wintypes.BOOL

kernel32.EndUpdateResourceW.argtypes = [wintypes.HANDLE, wintypes.BOOL]
kernel32.EndUpdateResourceW.restype = wintypes.BOOL


class NativeResourceError(RuntimeError):
    pass


def extract_resource(path: Path, resource_type: str, resource_id: int, language: int) -> bytes:
    module = kernel32.LoadLibraryExW(
        str(path),
        None,
        LOAD_LIBRARY_AS_DATAFILE | DONT_RESOLVE_DLL_REFERENCES,
    )
    if not module:
        raise NativeResourceError(_last_error("加载资源文件失败"))
    try:
        res_info = kernel32.FindResourceExW(module, resource_type, _make_int_resource(resource_id), language)
        if not res_info:
            raise NativeResourceError(_last_error("查找资源失败"))
        loaded = kernel32.LoadResource(module, res_info)
        if not loaded:
            raise NativeResourceError(_last_error("加载资源数据失败"))
        size = kernel32.SizeofResource(module, res_info)
        if not size:
            raise NativeResourceError(_last_error("资源大小无效"))
        data_ptr = kernel32.LockResource(loaded)
        if not data_ptr:
            raise NativeResourceError(_last_error("锁定资源数据失败"))
        return ctypes.string_at(data_ptr, size)
    finally:
        kernel32.FreeLibrary(module)


def replace_resource(path: Path, resource_type: str, resource_id: int, language: int, data: bytes) -> None:
    updater = kernel32.BeginUpdateResourceW(str(path), False)
    if not updater:
        raise NativeResourceError(_last_error("开始写入资源失败"))

    buffer = ctypes.create_string_buffer(data)
    try:
        updated = kernel32.UpdateResourceW(
            updater,
            resource_type,
            _make_int_resource(resource_id),
            language,
            buffer,
            len(data),
        )
        if not updated:
            raise NativeResourceError(_last_error("更新资源失败"))
        committed = kernel32.EndUpdateResourceW(updater, False)
        if not committed:
            raise NativeResourceError(_last_error("提交资源写入失败"))
    except Exception:
        kernel32.EndUpdateResourceW(updater, True)
        raise


def _make_int_resource(value: int) -> wintypes.LPCWSTR:
    return ctypes.cast(ctypes.c_void_p(value), wintypes.LPCWSTR)


def _last_error(prefix: str) -> str:
    return f"{prefix}，Win32 错误码: {ctypes.get_last_error()}"
