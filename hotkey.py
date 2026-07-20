# hotkey.py
import win32gui
import win32con
import win32api
import threading
import logging
import time

logger = logging.getLogger(__name__)

class HotkeyHandler:
    def __init__(self, callback, hotkey_str="F3"):
        self.callback = callback
        self.hotkey_str = hotkey_str
        self.hwnd = None
        self.hotkey_id = 1
        self.thread = None
        self.running = False
        self.registered = False

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.running = True
        self.thread = threading.Thread(target=self._thread_func, daemon=True)
        self.thread.start()
        logger.info("HotkeyHandler запущен")

    def stop(self):
        self.running = False
        if self.hwnd and win32gui.IsWindow(self.hwnd):
            win32gui.PostMessage(self.hwnd, win32con.WM_CLOSE, 0, 0)
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1)
        logger.info("HotkeyHandler остановлен")

    def _thread_func(self):
        # 1. Создаём скрытое окно
        wc = win32gui.WNDCLASS()
        wc.hInstance = win32api.GetModuleHandle(None)
        wc.lpszClassName = "HotkeyHandlerWindow"
        wc.lpfnWndProc = self._wnd_proc
        class_atom = win32gui.RegisterClass(wc)
        self.hwnd = win32gui.CreateWindow(
            class_atom, "HotkeyHandlerWindow",
            win32con.WS_OVERLAPPED,
            0, 0, 0, 0,
            0, 0,
            wc.hInstance,
            None
        )
        win32gui.UpdateWindow(self.hwnd)
        logger.debug(f"Окно хоткея создано, hwnd={self.hwnd}")

        # 2. Регистрируем хоткей
        vk = self._parse_vk(self.hotkey_str)
        if vk is None:
            logger.error(f"Неверная клавиша: {self.hotkey_str}")
            win32gui.DestroyWindow(self.hwnd)
            return
        try:
            win32gui.RegisterHotKey(self.hwnd, self.hotkey_id, 0, vk)
            self.registered = True
            logger.info(f"Хоткей {self.hotkey_str} зарегистрирован в HotkeyHandler")
        except Exception as e:
            logger.error(f"Ошибка регистрации хоткея: {e}")

        # 3. Цикл обработки сообщений (без MsgWaitForMultipleObjects)
        while self.running:
            win32gui.PumpWaitingMessages()
            if not win32gui.IsWindow(self.hwnd):
                break
            time.sleep(0.02)  # небольшая задержка, чтобы не грузить процессор

        # 4. Очистка
        if self.registered:
            try:
                win32gui.UnregisterHotKey(self.hwnd, self.hotkey_id)
            except:
                pass
        if win32gui.IsWindow(self.hwnd):
            win32gui.DestroyWindow(self.hwnd)
        logger.debug("HotkeyHandler поток завершён")

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == win32con.WM_DESTROY:
            win32gui.PostQuitMessage(0)
        elif msg == 0x0312:  # WM_HOTKEY
            logger.debug("WM_HOTKEY получен")
            if self.callback:
                try:
                    self.callback()
                except Exception as e:
                    logger.error(f"Ошибка в callback хоткея: {e}")
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def _parse_vk(self, key_str):
        key_str = key_str.strip().upper()
        vk_map = {
            'F1': win32con.VK_F1, 'F2': win32con.VK_F2, 'F3': win32con.VK_F3,
            'F4': win32con.VK_F4, 'F5': win32con.VK_F5, 'F6': win32con.VK_F6,
            'F7': win32con.VK_F7, 'F8': win32con.VK_F8, 'F9': win32con.VK_F9,
            'F10': win32con.VK_F10, 'F11': win32con.VK_F11, 'F12': win32con.VK_F12,
            'F13': win32con.VK_F13, 'F14': win32con.VK_F14, 'F15': win32con.VK_F15,
            'F16': win32con.VK_F16, 'F17': win32con.VK_F17, 'F18': win32con.VK_F18,
            'F19': win32con.VK_F19, 'F20': win32con.VK_F20, 'F21': win32con.VK_F21,
            'F22': win32con.VK_F22, 'F23': win32con.VK_F23, 'F24': win32con.VK_F24,
            'SPACE': win32con.VK_SPACE, 'ENTER': win32con.VK_RETURN,
            'ESC': win32con.VK_ESCAPE, 'TAB': win32con.VK_TAB,
            'BACKSPACE': win32con.VK_BACK, 'DELETE': win32con.VK_DELETE,
            'INSERT': win32con.VK_INSERT, 'HOME': win32con.VK_HOME,
            'END': win32con.VK_END, 'PAGEUP': win32con.VK_PRIOR,
            'PAGEDOWN': win32con.VK_NEXT,
            'UP': win32con.VK_UP, 'DOWN': win32con.VK_DOWN,
            'LEFT': win32con.VK_LEFT, 'RIGHT': win32con.VK_RIGHT,
        }
        for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            vk_map[c] = ord(c)
        for d in "0123456789":
            vk_map[d] = ord(d)
        return vk_map.get(key_str, None)