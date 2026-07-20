# tray_icon.py
import win32gui
import win32con
import win32api
import win32event  # <-- добавлен для MsgWaitForMultipleObjects
import os
import tempfile
import threading
import tkinter as tk
import logging
import queue
import time
from PIL import Image, ImageDraw

logger = logging.getLogger(__name__)

NIF_ICON = 0x00000002
NIF_MESSAGE = 0x00000001
NIF_TIP = 0x00000004
NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002
WM_TRAYICON = 0x8000 + 0x0400
WM_HOTKEY = 0x0312

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

_MODIFIER_WORDS = {
    'alt': MOD_ALT, 'left alt': MOD_ALT, 'right alt': MOD_ALT, 'altgr': MOD_ALT,
    'ctrl': MOD_CONTROL, 'control': MOD_CONTROL, 'left ctrl': MOD_CONTROL, 'right ctrl': MOD_CONTROL,
    'shift': MOD_SHIFT, 'left shift': MOD_SHIFT, 'right shift': MOD_SHIFT,
    'win': MOD_WIN, 'windows': MOD_WIN, 'super': MOD_WIN,
    'left windows': MOD_WIN, 'right windows': MOD_WIN, 'left win': MOD_WIN, 'right win': MOD_WIN,
}

_VK_MAP = {
    'capslock': win32con.VK_CAPITAL,
    'numlock': win32con.VK_NUMLOCK,
    'scrolllock': win32con.VK_SCROLL,
    'tab': win32con.VK_TAB,
    'space': win32con.VK_SPACE,
    'spacebar': win32con.VK_SPACE,
    'enter': win32con.VK_RETURN,
    'return': win32con.VK_RETURN,
    'esc': win32con.VK_ESCAPE,
    'escape': win32con.VK_ESCAPE,
    'backspace': win32con.VK_BACK,
    'delete': win32con.VK_DELETE,
    'insert': win32con.VK_INSERT,
    'home': win32con.VK_HOME,
    'end': win32con.VK_END,
    'pageup': win32con.VK_PRIOR,
    'pagedown': win32con.VK_NEXT,
    'up': win32con.VK_UP,
    'down': win32con.VK_DOWN,
    'left': win32con.VK_LEFT,
    'right': win32con.VK_RIGHT,
}
for _i in range(1, 25):
    _VK_MAP[f'f{_i}'] = getattr(win32con, f'VK_F{_i}', None)
_VK_MAP = {k: v for k, v in _VK_MAP.items() if v is not None}
for _c in "abcdefghijklmnopqrstuvwxyz":
    _VK_MAP[_c] = ord(_c.upper())
for _d in "0123456789":
    _VK_MAP[_d] = ord(_d)

class TrayIcon:
    def __init__(self, app, root, hotkey="f9"):
        logger.debug("TrayIcon.__init__: начало")
        self.app = app
        self.root = root
        self.hotkey = hotkey
        self.hwnd = None
        self.icon_id = 1
        self.hotkey_id = 1
        self.hotkey_registered = False
        self.is_recording = False
        self.thread = None
        self.running = False
        self.icon_green = None
        self.icon_red = None
        self.icon_yellow = None

        self.last_hotkey_time = 0
        self.hotkey_debounce_ms = 500

        self.cmd_queue = queue.Queue(maxsize=1)
        self.critical_queue = queue.Queue()

        self._process_queues()
        logger.debug("TrayIcon.__init__: завершено")

    def _process_queues(self):
        while True:
            try:
                cmd = self.critical_queue.get_nowait()
                logger.debug(f"_process_queues: критическая команда {cmd}")
                self._dispatch(cmd)
            except queue.Empty:
                break

        try:
            cmd = self.cmd_queue.get_nowait()
            logger.debug(f"_process_queues: обычная команда {cmd}")
            self._dispatch(cmd)
        except queue.Empty:
            pass

        self.root.after(100, self._process_queues)

    def _dispatch(self, cmd):
        logger.debug(f"_dispatch: {cmd}")
        if cmd[0] == 'toggle':
            self._toggle_window()
        elif cmd[0] == 'menu':
            self._show_context_menu()
        elif cmd[0] == 'open_settings':
            self.app.open_settings()
        elif cmd[0] == 'quit':
            self._quit_app()
        elif cmd[0] == 'restart':
            self.app.restart_program()
        elif cmd[0] == 'update_state':
            self._update_state(cmd[1])
        elif cmd[0] == 'hotkey_record':
            self.app.hotkey_toggle()

    def _send_command(self, cmd):
        cmd_type = cmd[0]
        if cmd_type in ('update_state', 'quit', 'restart', 'hotkey_record'):
            logger.debug(f"_send_command: критическая команда {cmd}")
            self.critical_queue.put(cmd)
        else:
            try:
                self.cmd_queue.put_nowait(cmd)
                logger.debug(f"_send_command: команда {cmd} добавлена в очередь")
            except queue.Full:
                logger.debug(f"Команда {cmd} пропущена (очередь занята)")

    def _parse_hotkey(self, hotkey_str):
        try:
            parts = [p.strip().lower() for p in hotkey_str.split('+') if p.strip()]
            if not parts:
                return None
            modifiers = 0
            key_token = None
            for part in parts:
                if part in _MODIFIER_WORDS:
                    modifiers |= _MODIFIER_WORDS[part]
                else:
                    key_token = part

            if key_token is None:
                logger.error(f"_parse_hotkey: в хоткее '{hotkey_str}' не найдена основная клавиша")
                return None

            key_lookup = key_token.replace(' ', '')
            vk = _VK_MAP.get(key_lookup)
            if vk is None:
                logger.error(f"_parse_hotkey: неизвестная клавиша '{key_token}' в хоткее '{hotkey_str}'")
                return None

            return modifiers | MOD_NOREPEAT, vk
        except Exception as e:
            logger.error(f"_parse_hotkey: ошибка разбора '{hotkey_str}': {e}", exc_info=True)
            return None

    def _register_hotkey(self):
        parsed = self._parse_hotkey(self.hotkey)
        if parsed is None:
            logger.error(f"Не удалось зарегистрировать хоткей '{self.hotkey}': не распознан формат.")
            return
        modifiers, vk = parsed
        try:
            win32gui.RegisterHotKey(self.hwnd, self.hotkey_id, modifiers, vk)
            self.hotkey_registered = True
            logger.info(f"Глобальный хоткей '{self.hotkey}' зарегистрирован через RegisterHotKey.")
        except Exception as e:
            self.hotkey_registered = False
            logger.error(
                f"Не удалось зарегистрировать хоткей '{self.hotkey}' "
                f"(возможно, комбинация уже занята другой программой): {e}",
                exc_info=True
            )

    def _unregister_hotkey(self):
        if self.hotkey_registered and self.hwnd:
            try:
                win32gui.UnregisterHotKey(self.hwnd, self.hotkey_id)
                logger.debug("_unregister_hotkey: хоткей снят")
            except Exception as e:
                logger.warning(f"Не удалось снять регистрацию хоткея: {e}")
            self.hotkey_registered = False

    def create_icon_images(self):
        logger.debug("create_icon_images: создание иконок")
        size = 64
        img_green = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img_green)
        draw.ellipse((8, 8, size-8, size-8), fill='#32cd32', outline='#228b22', width=2)

        img_red = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img_red)
        draw.ellipse((8, 8, size-8, size-8), fill='#ff3333', outline='#cc0000', width=2)

        img_yellow = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img_yellow)
        draw.ellipse((8, 8, size-8, size-8), fill='#ffc107', outline='#b38600', width=2)

        self.icon_green = self._pil_to_icon(img_green)
        self.icon_red = self._pil_to_icon(img_red)
        self.icon_yellow = self._pil_to_icon(img_yellow)
        logger.debug("create_icon_images: иконки созданы")

    def _pil_to_icon(self, pil_img):
        with tempfile.NamedTemporaryFile(suffix='.ico', delete=False) as f:
            temp_path = f.name
            pil_img.save(temp_path, format='ico', sizes=[(64, 64)])
        try:
            hicon = win32gui.LoadImage(
                0,
                temp_path,
                win32con.IMAGE_ICON,
                0, 0,
                win32con.LR_LOADFROMFILE | win32con.LR_DEFAULTSIZE
            )
            if hicon == 0:
                raise RuntimeError("LoadImage вернул 0")
            return hicon
        finally:
            try:
                os.unlink(temp_path)
            except:
                pass

    def _create_window(self):
        logger.debug("_create_window: создание окна для трея")
        wc = win32gui.WNDCLASS()
        wc.hInstance = win32api.GetModuleHandle(None)
        wc.lpszClassName = "TrayIconWindow"
        wc.lpfnWndProc = self._wnd_proc
        class_atom = win32gui.RegisterClass(wc)
        self.hwnd = win32gui.CreateWindow(
            class_atom, "TrayIconWindow",
            win32con.WS_OVERLAPPED,
            0, 0, 0, 0,
            0, 0,
            wc.hInstance,
            None
        )
        win32gui.UpdateWindow(self.hwnd)
        logger.debug("_create_window: окно создано")

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == win32con.WM_DESTROY:
            win32gui.PostQuitMessage(0)
        elif msg == WM_HOTKEY:
            if wparam == self.hotkey_id:
                now = time.time() * 1000
                if now - self.last_hotkey_time >= self.hotkey_debounce_ms:
                    self.last_hotkey_time = now
                    logger.debug("WM_HOTKEY: сработал зарегистрированный глобальный хоткей")
                    self._send_command(('hotkey_record',))
                else:
                    logger.debug("WM_HOTKEY: подавлен (debounce)")
        elif msg == WM_TRAYICON:
            if lparam == win32con.WM_LBUTTONUP:
                logger.debug("WM_TRAYICON: левая кнопка")
                self._send_command(('toggle',))
            elif lparam == win32con.WM_RBUTTONUP:
                logger.debug("WM_TRAYICON: правая кнопка")
                self._send_command(('menu',))
        elif msg == win32con.WM_COMMAND:
            cmd = wparam & 0xFFFF
            logger.debug(f"WM_COMMAND: {cmd}")
            if cmd == 1001:
                self._send_command(('toggle',))
            elif cmd == 1002:
                self._send_command(('open_settings',))
            elif cmd == 1003:
                self._send_command(('quit',))
            elif cmd == 1004:
                self._send_command(('restart',))
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def _show_context_menu(self):
        logger.debug("_show_context_menu: показ контекстного меню")
        menu = win32gui.CreatePopupMenu()
        win32gui.AppendMenu(menu, win32con.MF_STRING, 1001, "Показать/Скрыть окно")
        win32gui.AppendMenu(menu, win32con.MF_STRING, 1002, "Настройки")
        win32gui.AppendMenu(menu, win32con.MF_STRING, 1004, "Перезапустить")
        win32gui.AppendMenu(menu, win32con.MF_STRING, 1003, "Выход")
        cursor = win32api.GetCursorPos()

        try:
            if win32gui.IsWindow(self.hwnd):
                win32gui.SetForegroundWindow(self.hwnd)
        except Exception as e:
            logger.debug(f"SetForegroundWindow не удался: {e}")

        win32gui.TrackPopupMenu(menu, win32con.TPM_LEFTALIGN | win32con.TPM_RIGHTBUTTON,
                                cursor[0], cursor[1], 0, self.hwnd, None)
        win32gui.DestroyMenu(menu)
        win32gui.PostMessage(self.hwnd, win32con.WM_NULL, 0, 0)

    def setup(self):
        logger.debug("setup: настройка трея")
        self.create_icon_images()
        self._create_window()
        self._add_icon_to_tray()
        self._register_hotkey()
        self.running = True
        self.thread = threading.Thread(target=self._message_loop, daemon=True)
        self.thread.start()
        logger.info("Трей иконка запущена")

    def _add_icon_to_tray(self):
        nid = (self.hwnd, self.icon_id, NIF_ICON | NIF_MESSAGE | NIF_TIP,
               WM_TRAYICON, self.icon_green, f"Диктофон → Текст ({self.hotkey})")
        win32gui.Shell_NotifyIcon(NIM_ADD, nid)
        self.nid = nid
        logger.debug("_add_icon_to_tray: иконка добавлена")

    def _update_tray_icon(self, icon):
        nid = (self.hwnd, self.icon_id, NIF_ICON,
               WM_TRAYICON, icon, "")
        win32gui.Shell_NotifyIcon(NIM_MODIFY, nid)
        logger.debug("_update_tray_icon: иконка обновлена")

    # ========== ИСПРАВЛЕННЫЙ МЕТОД ==========
    def _message_loop(self):
        while self.running:
            win32gui.PumpWaitingMessages()
            if not win32gui.IsWindow(self.hwnd):
                break
            # Блокируем поток до появления сообщения или истечения 20 мс
            win32event.MsgWaitForMultipleObjects(0, [], False, 20, win32event.QS_ALLINPUT)
        win32gui.DestroyWindow(self.hwnd)

    def _toggle_window(self):
        logger.debug("_toggle_window: переключение видимости через трей")
        self.app.toggle_visibility()

    def _quit_app(self):
        logger.info("Выход из программы")
        self.running = False
        self._unregister_hotkey()
        self.remove_icon()
        self.root.quit()

    def remove_icon(self):
        logger.debug("remove_icon: удаление иконки")
        try:
            nid = (self.hwnd, self.icon_id, 0, 0, 0, "")
            win32gui.Shell_NotifyIcon(NIM_DELETE, nid)
            logger.debug("remove_icon: иконка удалена")
        except Exception as e:
            logger.warning(f"Не удалось удалить иконку: {e}")

    def shutdown(self):
        self._unregister_hotkey()
        self.remove_icon()

    def update_state(self, state):
        self._send_command(('update_state', state))

    def _update_state(self, state):
        logger.debug(f"_update_state: state={state}")
        if state == 'processing':
            self.is_recording = False
            self._update_tray_icon(self.icon_yellow)
        elif state:
            self.is_recording = True
            self._update_tray_icon(self.icon_red)
        else:
            self.is_recording = False
            self._update_tray_icon(self.icon_green)