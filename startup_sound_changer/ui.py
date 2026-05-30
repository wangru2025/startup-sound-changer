from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
import traceback
import winsound

import wx

from .audio import convert_to_wav
from .audio import supported_extensions
from .constants import APP_NAME, ERROR_LOG_NAME, IMAGERES_PATH, PREVIEW_NAME, app_data_dir
from .presets import SHUTDOWN_SOUND_PRESETS, SOUND_PRESETS
from .shutdown import apply_shutdown_sound, remove_shutdown_sound, shutdown_sound_installed
from .tasks import apply_startup_sound, restore_startup_sound
from .system_ops import ensure_admin

SCREEN_HOME = "home"
SCREEN_STARTUP = "startup"
SCREEN_SHUTDOWN = "shutdown"


class WarningDialog(wx.Dialog):
    def __init__(self, parent: wx.Window) -> None:
        super().__init__(parent=parent, title="\u8b66\u544a", size=(560, 360))
        root = wx.BoxSizer(wx.VERTICAL)
        text = wx.TextCtrl(
            self,
            value=(
                "Windows 8、Windows 10 和 Windows 11 已经不再提供以前那种稳定的系统关机声音入口。\n\n"
                "应用后，本工具会保存你选择的声音，并在用户登录时准备好播放环境。系统准备关机或重启时，会先通知一个负责协调关机前任务的系统组件；它会尽量争取一小段等待时间，让当前用户会话把声音播放完，然后再让 Windows 继续完成关机或重启。\n\n"
                "这个方案不会替换系统文件，也不会接管电源按钮。它只是利用 Windows 允许程序在关机前完成收尾工作的机制来播放声音。正常从开始菜单、快捷键菜单或命令发起的关机/重启通常都可以触发；但强制关机、断电、长按电源键、系统更新、音频服务异常或 Windows 等待超时，仍然可能导致声音没有播放或没有完整播放。\n\n"
                "删除关机音会同时清理保存的音频、配置、开机自启动项和关机前协调组件。"
            ),
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_WORDWRAP,
        )
        root.Add(text, 1, wx.ALL | wx.EXPAND, 12)
        button = wx.Button(self, wx.ID_OK, label="\u6211\u77e5\u9053\u4e86\uff0c\u5f00\u59cb\u5e94\u7528")
        root.Add(button, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.ALIGN_RIGHT, 12)
        self.SetSizer(root)
        self.CentreOnParent()


class MainFrame(wx.Frame):
    def __init__(self) -> None:
        super().__init__(parent=None, title=APP_NAME, size=(760, 560))
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="worker")
        self.preview_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="preview")
        self.operation_busy = False
        self.preview_busy = False
        self.screen = SCREEN_HOME
        self.panel: wx.Panel | None = None
        self.log: wx.TextCtrl | None = None
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.show_home()
        self.Centre()

    def show_home(self) -> None:
        self._replace_panel()
        self.screen = SCREEN_HOME
        self.SetTitle(APP_NAME)
        self.log = None

        root = wx.BoxSizer(wx.VERTICAL)
        title = wx.StaticText(self.panel, label="\u9009\u62e9\u8981\u8bbe\u7f6e\u7684\u7cfb\u7edf\u58f0\u97f3")
        title_font = title.GetFont()
        title_font.SetPointSize(14)
        title_font.SetWeight(wx.FONTWEIGHT_BOLD)
        title.SetFont(title_font)
        root.AddStretchSpacer(1)
        root.Add(title, 0, wx.ALIGN_CENTER | wx.BOTTOM, 18)

        startup_button = wx.Button(self.panel, label="\u8bbe\u7f6e\u5f00\u673a\u97f3", size=(220, 44))
        shutdown_button = wx.Button(self.panel, label="\u8bbe\u7f6e\u5173\u673a\u97f3", size=(220, 44))
        root.Add(startup_button, 0, wx.ALIGN_CENTER | wx.BOTTOM, 12)
        root.Add(shutdown_button, 0, wx.ALIGN_CENTER)
        root.AddStretchSpacer(1)

        startup_button.Bind(wx.EVT_BUTTON, lambda _event: self.show_sound_panel(SCREEN_STARTUP))
        shutdown_button.Bind(wx.EVT_BUTTON, lambda _event: self.show_sound_panel(SCREEN_SHUTDOWN))
        self.panel.SetSizer(root)
        self.Layout()

    def show_sound_panel(self, screen: str) -> None:
        self._replace_panel()
        self.screen = screen
        self.operation_busy = False
        self.preview_busy = False
        is_shutdown = screen == SCREEN_SHUTDOWN
        presets = SHUTDOWN_SOUND_PRESETS if is_shutdown else SOUND_PRESETS
        self.current_presets = presets
        self.SetTitle(f"{APP_NAME} - {'\u5173\u673a\u97f3' if is_shutdown else '\u5f00\u673a\u97f3'}")

        root = wx.BoxSizer(wx.VERTICAL)
        intro_label = (
            "\u8bbe\u7f6e\u5173\u673a\u58f0\u97f3\u3002\u5e94\u7528\u540e\u4f1a\u5728\u5f53\u524d\u7528\u6237\u914d\u7f6e\u76ee\u5f55\u4fdd\u5b58\u97f3\u9891\u548c\u8bbe\u7f6e\u3002"
            if is_shutdown
            else "\u76f4\u63a5\u4fee\u6539 imageres.dll \u5185\u7684\u542f\u52a8\u58f0\u97f3\u8d44\u6e90\uff0c\u4e0d\u518d\u4f7f\u7528 Resource Hacker\u3002"
        )
        intro = wx.StaticText(self.panel, label=intro_label)
        intro.Wrap(700)
        root.Add(intro, 0, wx.ALL | wx.EXPAND, 12)

        preset_labels = ["\u81ea\u5b9a\u4e49\u6587\u4ef6"] + [preset.label for preset in presets]
        self.sound_choice = wx.RadioBox(
            self.panel,
            label="\u5173\u673a\u58f0\u97f3\u6765\u6e90" if is_shutdown else "\u542f\u52a8\u58f0\u97f3\u6765\u6e90",
            choices=preset_labels,
            majorDimension=1,
            style=wx.RA_SPECIFY_COLS,
        )
        root.Add(self.sound_choice, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        picker_wildcard = "\u97f3\u9891\u6587\u4ef6|" + ";".join(f"*.{ext}" for ext in supported_extensions()) + "|\u6240\u6709\u6587\u4ef6|*.*"
        self.file_picker = wx.FilePickerCtrl(self.panel, message="\u9009\u62e9\u97f3\u9891\u6587\u4ef6", wildcard=picker_wildcard)
        root.Add(self.file_picker, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        button_row = wx.BoxSizer(wx.HORIZONTAL)
        self.preview_button = wx.Button(self.panel, label="\u8bd5\u542c")
        self.apply_button = wx.Button(self.panel, label="\u5e94\u7528\u5173\u673a\u58f0\u97f3" if is_shutdown else "\u5e94\u7528\u542f\u52a8\u58f0\u97f3")
        button_row.Add(self.preview_button, 0, wx.RIGHT, 8)
        button_row.Add(self.apply_button, 0, wx.RIGHT, 8)

        self.restore_button = None
        self.delete_shutdown_button = None
        if is_shutdown:
            self.delete_shutdown_button = wx.Button(self.panel, label="\u5220\u9664\u5173\u673a\u97f3")
            self.delete_shutdown_button.Show(shutdown_sound_installed())
            self.delete_shutdown_button.Bind(wx.EVT_BUTTON, self.on_delete_shutdown)
            button_row.Add(self.delete_shutdown_button, 0, wx.RIGHT, 8)
        else:
            self.restore_button = wx.Button(self.panel, label="\u6062\u590d\u5907\u4efd")
            self.restore_button.Bind(wx.EVT_BUTTON, self.on_restore)
            button_row.Add(self.restore_button, 0, wx.RIGHT, 8)

        self.open_workspace_button = wx.Button(self.panel, label="\u6253\u5f00\u5de5\u4f5c\u76ee\u5f55")
        button_row.Add(self.open_workspace_button, 0)
        root.Add(button_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        if is_shutdown:
            info_label = f"\u914d\u7f6e\u76ee\u5f55: {app_data_dir()}"
        else:
            info_label = f"\u7cfb\u7edf\u76ee\u6807\u6587\u4ef6: {IMAGERES_PATH}\n\u5de5\u4f5c\u76ee\u5f55: {app_data_dir()}"
        info = wx.StaticText(self.panel, label=info_label)
        root.Add(info, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        self.log = wx.TextCtrl(self.panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL)
        root.Add(self.log, 1, wx.ALL | wx.EXPAND, 12)

        self.panel.SetSizer(root)
        self.sound_choice.Bind(wx.EVT_RADIOBOX, self.on_sound_choice)
        self.preview_button.Bind(wx.EVT_BUTTON, self.on_preview)
        self.apply_button.Bind(wx.EVT_BUTTON, self.on_apply)
        self.open_workspace_button.Bind(wx.EVT_BUTTON, self.on_open_workspace)
        self._update_source_controls()
        self._append_log(f"\u5f53\u524d\u7ba1\u7406\u5458\u6743\u9650: {'\u662f' if ensure_admin() else '\u5426'}")
        self.Layout()

    def on_apply(self, _event: wx.CommandEvent) -> None:
        path = self._selected_audio_path()
        if not path.exists():
            self._append_log("\u8bf7\u5148\u9009\u62e9\u6709\u6548\u7684\u97f3\u9891\u6587\u4ef6\u3002")
            return
        if self.screen == SCREEN_SHUTDOWN:
            with WarningDialog(self) as dialog:
                if dialog.ShowModal() != wx.ID_OK:
                    return
            self._set_busy(True)
            self._append_log(f"\u5f00\u59cb\u5e94\u7528\u5173\u673a\u58f0\u97f3: {path}")
            future = self.executor.submit(apply_shutdown_sound, path)
            future.sound_screen = self.screen
            future.add_done_callback(self._finish_apply)
            return

        self._set_busy(True)
        self._append_log(f"\u5f00\u59cb\u5e94\u7528\u542f\u52a8\u58f0\u97f3: {path}")
        future = self.executor.submit(apply_startup_sound, path)
        future.sound_screen = self.screen
        future.add_done_callback(self._finish_apply)

    def on_preview(self, _event: wx.CommandEvent) -> None:
        path = self._selected_audio_path()
        if not path.exists():
            self._append_log("\u8bf7\u5148\u9009\u62e9\u6709\u6548\u7684\u97f3\u9891\u6587\u4ef6\u3002")
            return
        self.preview_busy = True
        self._update_source_controls()
        self._append_log(f"\u5f00\u59cb\u8bd5\u542c: {path}")
        future = self.preview_executor.submit(_play_preview, path)
        future.sound_screen = self.screen
        future.add_done_callback(self._finish_preview)

    def on_restore(self, _event: wx.CommandEvent) -> None:
        self._set_busy(True)
        self._append_log("\u5f00\u59cb\u6062\u590d\u5907\u4efd\u8d44\u6e90\u6587\u4ef6\u3002")
        future = self.executor.submit(restore_startup_sound)
        future.sound_screen = self.screen
        future.add_done_callback(self._finish_restore)

    def on_delete_shutdown(self, _event: wx.CommandEvent) -> None:
        self._set_busy(True)
        self._append_log("\u5f00\u59cb\u5220\u9664\u5173\u673a\u97f3\u914d\u7f6e\u3002")
        future = self.executor.submit(remove_shutdown_sound)
        future.sound_screen = self.screen
        future.add_done_callback(self._finish_delete_shutdown)

    def on_sound_choice(self, _event: wx.CommandEvent) -> None:
        self._update_source_controls()

    def on_open_workspace(self, _event: wx.CommandEvent) -> None:
        app_data_dir().mkdir(parents=True, exist_ok=True)
        wx.LaunchDefaultApplication(str(app_data_dir()))

    def on_close(self, event: wx.CloseEvent) -> None:
        if self.screen != SCREEN_HOME:
            event.Veto()
            winsound.PlaySound(None, 0)
            self.show_home()
            return
        winsound.PlaySound(None, 0)
        self.preview_executor.shutdown(wait=False, cancel_futures=True)
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.Destroy()

    def _finish_apply(self, future: Future) -> None:
        wx.CallAfter(self._handle_apply_result, future, getattr(future, "sound_screen", self.screen))

    def _finish_restore(self, future: Future) -> None:
        wx.CallAfter(self._handle_restore_result, future, getattr(future, "sound_screen", self.screen))

    def _finish_preview(self, future: Future) -> None:
        wx.CallAfter(self._handle_preview_result, future, getattr(future, "sound_screen", self.screen))

    def _finish_delete_shutdown(self, future: Future) -> None:
        wx.CallAfter(self._handle_delete_shutdown_result, future, getattr(future, "sound_screen", self.screen))

    def _handle_apply_result(self, future: Future, screen: str) -> None:
        if self.screen == SCREEN_HOME or self.screen != screen:
            return
        self._set_busy(False)
        try:
            result = future.result()
        except Exception as exc:
            action = "\u5e94\u7528\u5173\u673a\u58f0\u97f3" if screen == SCREEN_SHUTDOWN else "\u5e94\u7528\u542f\u52a8\u58f0\u97f3"
            self._append_log(f"\u5e94\u7528\u5931\u8d25: {exc}")
            self._write_error_log(action, exc)
            return

        if screen == SCREEN_SHUTDOWN:
            self._append_log(f"\u5173\u673a\u58f0\u97f3\u6587\u4ef6: {result.sound_file}")
            self._append_log(f"\u914d\u7f6e\u6587\u4ef6: {result.settings_file}")
            self._append_log(f"\u7cfb\u7edf\u670d\u52a1: {result.service_name}")
            self._append_log("\u5173\u673a\u58f0\u97f3\u5e94\u7528\u5b8c\u6210\u3002")
            if self.delete_shutdown_button is not None:
                self.delete_shutdown_button.Show(True)
                self.Layout()
            return

        self._append_log(f"\u8f6c\u6362\u540e\u7684 WAV: {result.converted_wav}")
        self._append_log(f"\u751f\u6210\u7684\u8865\u4e01 DLL: {result.patched_file}")
        self._append_log(f"\u7cfb\u7edf\u5907\u4efd\u6587\u4ef6: {result.backup_file}")
        self._append_log("\u542f\u52a8\u58f0\u97f3\u66ff\u6362\u5b8c\u6210\u3002")

    def _handle_restore_result(self, future: Future, screen: str) -> None:
        if self.screen == SCREEN_HOME or self.screen != screen:
            return
        self._set_busy(False)
        try:
            backup = future.result()
        except Exception as exc:
            self._append_log(f"\u6062\u590d\u5931\u8d25: {exc}")
            self._write_error_log("\u6062\u590d\u542f\u52a8\u58f0\u97f3", exc)
            return
        self._append_log(f"\u5df2\u6062\u590d\u5230\u7cfb\u7edf\u6587\u4ef6: {backup}")

    def _handle_preview_result(self, future: Future, screen: str) -> None:
        if self.screen == SCREEN_HOME or self.screen != screen:
            return
        self.preview_busy = False
        self._update_source_controls()
        try:
            future.result()
        except Exception as exc:
            self._append_log(f"\u8bd5\u542c\u5931\u8d25: {exc}")
            self._write_error_log("\u8bd5\u542c\u58f0\u97f3", exc)
            return
        self._append_log("\u8bd5\u542c\u7ed3\u675f\u3002")

    def _handle_delete_shutdown_result(self, future: Future, screen: str) -> None:
        if self.screen == SCREEN_HOME or self.screen != screen:
            return
        self._set_busy(False)
        try:
            future.result()
        except Exception as exc:
            self._append_log(f"\u5220\u9664\u5931\u8d25: {exc}")
            self._write_error_log("\u5220\u9664\u5173\u673a\u97f3", exc)
            return
        self._append_log("\u5173\u673a\u97f3\u914d\u7f6e\u5df2\u5220\u9664\u3002")
        if self.delete_shutdown_button is not None:
            self.delete_shutdown_button.Show(False)
            self.Layout()

    def _selected_audio_path(self) -> Path:
        selection = self.sound_choice.GetSelection()
        if selection <= 0:
            return Path(self.file_picker.GetPath())
        return self.current_presets[selection - 1].path

    def _update_source_controls(self) -> None:
        if self.screen == SCREEN_HOME:
            return
        is_custom = self.sound_choice.GetSelection() == 0
        controls_enabled = not self.operation_busy
        self.sound_choice.Enable(controls_enabled)
        self.file_picker.Enable(is_custom and controls_enabled)
        self.preview_button.Enable(controls_enabled and not self.preview_busy)
        self.apply_button.Enable(controls_enabled)
        if self.restore_button is not None:
            self.restore_button.Enable(controls_enabled)
        if self.delete_shutdown_button is not None:
            self.delete_shutdown_button.Enable(controls_enabled)

    def _append_log(self, message: str) -> None:
        if self.log is None:
            return
        self.log.AppendText(message.rstrip() + "\n")

    def _write_error_log(self, action: str, exc: Exception) -> None:
        log_path = app_data_dir() / ERROR_LOG_NAME
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(f"[{action}]\n")
            fh.write(traceback.format_exc())
            fh.write("\n")
        self._append_log(f"\u8be6\u7ec6\u9519\u8bef\u5df2\u5199\u5165: {log_path}")

    def _set_busy(self, busy: bool) -> None:
        self.operation_busy = busy
        self._update_source_controls()

    def _replace_panel(self) -> None:
        if self.panel is not None:
            self.panel.Destroy()
        self.panel = wx.Panel(self)


def _play_preview(path: Path) -> None:
    preview_wav = convert_to_wav(path, app_data_dir(), target_name=PREVIEW_NAME)
    winsound.PlaySound(str(preview_wav), winsound.SND_FILENAME)


class StartupSoundApp(wx.App):
    def OnInit(self) -> bool:
        frame = MainFrame()
        frame.Show()
        return True
