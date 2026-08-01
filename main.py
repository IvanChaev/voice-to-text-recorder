# main.py
import os
import sys
import ctypes
import faulthandler

# ========== ЗАЩИТА ОТ ДВУХ ЗАПУЩЕННЫХ ЭКЗЕМПЛЯРОВ ==========
# Именованный мьютекс Windows: второй экземпляр программы завершается сразу,
# ещё до тяжёлых импортов. Это исключает ситуацию двух одновременно
# запущенных копий (например, когда watchdog перезапускает программу,
# а прошлая копия ещё грузится и не успела создать pid-файл).
_SINGLE_INSTANCE_NAME = "Local\\my_voice_project_single_instance"
_single_instance_handle = None

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
_kernel32.CreateMutexW.restype = ctypes.c_void_p
_kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
_kernel32.CloseHandle.restype = ctypes.c_bool

def acquire_single_instance():
    """Захватывает именованный мьютекс. True - экземпляр единственный."""
    global _single_instance_handle
    try:
        _single_instance_handle = _kernel32.CreateMutexW(None, False, _SINGLE_INSTANCE_NAME)
        if not _single_instance_handle:
            return True
        if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
            _kernel32.CloseHandle(_single_instance_handle)
            _single_instance_handle = None
            return False
        return True
    except Exception:
        _single_instance_handle = None
        return True  # при сбое не блокируем запуск

def release_single_instance():
    """Освобождает мьютекс при корректном завершении."""
    global _single_instance_handle
    if _single_instance_handle:
        try:
            _kernel32.CloseHandle(_single_instance_handle)
        except Exception:
            pass
        _single_instance_handle = None

if not acquire_single_instance():
    sys.exit(0)
# =================================================================

# ========== ПЕРЕХВАТ СЕГФОЛТОВ (краши в C-расширениях) ==========
_CRASH_LOG = os.path.join("logs", "crash_dump.log")
os.makedirs("logs", exist_ok=True)
faulthandler.enable(file=open(_CRASH_LOG, "ab", buffering=0), all_threads=True)
# =================================================================

APP_VERSION = "1.2.2"

import sys
import json
import logging
import psutil
import traceback
import gc
from datetime import datetime

sys.modules.setdefault("main", sys.modules[__name__])

LOG_DIR = "logs"
SESSION_START_TIME = datetime.now()
LOG_FILENAME = os.path.join(LOG_DIR, f"app_{SESSION_START_TIME:%Y-%m-%d_%H-%M-%S}.log")
LOG_LEVEL = "DEBUG"
LOG_KEEP_SESSIONS = 20

from logger_utils import setup_logging, shutdown_logging, log_time, log_exception, clear_restart_flag

setup_logging(LOG_FILENAME, LOG_LEVEL, log_dir=LOG_DIR, keep_sessions=LOG_KEEP_SESSIONS)
logger_pid = logging.getLogger("PIDManager")

# ---------- ДЕФОЛТНЫЕ НАСТРОЙКИ (large-v3-turbo + int8_float16) ----------
DEFAULT_SETTINGS = {
    "model_size": "large-v3-turbo",
    "device": "cuda",
    "compute_type": "int8_float16",
    "beam_size": 5,
    "sample_rate": 16000,
    "language": "auto",
    "autostart": False,
    "hotkey": "left alt+caps lock",
    "input_device": None,
    "gain_db": 10.0,
    "normalize": True,
    "noise_reduction": False,
    "noise_reduction_strength": 0.8,
    "enable_time_stretch": False,
    "speed_rate": 1.0,
    "silence_before_sec": 1.0,
    "silence_after_sec": 1.0,
    "silence_threshold": 5.0,
    "silence_timeout_sec": 20.0
}

SETTINGS_FILE = "settings.json"

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
                for key, value in DEFAULT_SETTINGS.items():
                    if key not in loaded:
                        loaded[key] = value
                return loaded
        except Exception as e:
            logger_pid.error(f"Сбой парсинга настроек JSON: {e}", exc_info=True)
            return DEFAULT_SETTINGS.copy()
    else:
        save_settings(DEFAULT_SETTINGS)
        return DEFAULT_SETTINGS.copy()

def save_settings(settings_dict):
    try:
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings_dict, f, indent=4, ensure_ascii=False)
        logger_pid.info("Настройки приложения обновлены на диске.")
    except Exception as e:
        logger_pid.error(f"Не удалось сериализовать настройки в JSON: {e}", exc_info=True)

from faster_whisper import WhisperModel

class Transcriber:
    def __init__(self, model_size="medium", device="cuda", compute_type="int8_float16", beam_size=5):
        self.logger = logging.getLogger("Transcriber")
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.beam_size = beam_size
        self.model = None
        self.load_model()

    def load_model(self):
        self.logger.info(f"Загрузка Whisper: {self.model_size} | Устройство: {self.device} | Вычисления: {self.compute_type}")
        self.model = WhisperModel(
            model_size_or_path=self.model_size,
            device=self.device,
            compute_type=self.compute_type
        )

    def transcribe(self, audio_data, retry=True):
        if audio_data is None or len(audio_data) == 0:
            self.logger.warning("Пустой массив на входе декодера.")
            return "", "unknown", 0.0

        try:
            segments, info = self.model.transcribe(
                audio_data,
                beam_size=self.beam_size,
                vad_filter=True
            )
            text = " ".join(segment.text for segment in segments)
            return text, info.language, info.language_probability
        except Exception as e:
            # Если ошибка связана с CUDA / GPU / памятью и это первая попытка
            if retry and ("cuda" in str(e).lower() or "cublas" in str(e).lower() or
                          "memory" in str(e).lower() or "driver" in str(e).lower()):
                self.logger.warning("Обнаружен сбой CUDA (возможно, после выхода из сна). Перезагружаем модель...")
                try:
                    del self.model
                except:
                    pass
                gc.collect()
                self.load_model()
                # Повторяем транскрипцию без retry, чтобы избежать бесконечного цикла
                return self.transcribe(audio_data, retry=False)
            else:
                # Иначе пробрасываем исключение
                raise

# ---------- PID-менеджмент ----------
PID_FILE = os.path.join(LOG_DIR, "pid.pid")

def check_and_clean_pid():
    logger_pid.debug("Проверка дубликатов процесса...")
    if not os.path.exists(PID_FILE):
        return
    try:
        with open(PID_FILE, 'r', encoding='utf-8') as f:
            pid_str = f.read().strip()
        if not pid_str:
            os.remove(PID_FILE)
            return
        pid = int(pid_str)
        if not psutil.pid_exists(pid):
            logger_pid.info(f"Мертвый PID {pid} обнаружен в конфигурации, очищаем.")
            os.remove(PID_FILE)
            return

        proc = psutil.Process(pid)
        proc_name = proc.name().lower()
        if 'python' not in proc_name:
            os.remove(PID_FILE)
            return

        cmdline = proc.cmdline()
        if 'main.py' not in ' '.join(cmdline):
            os.remove(PID_FILE)
            return

        logger_pid.info(f"Обнаружен работающий дубликат процесса (PID: {pid}). Завершаем...")
        proc.terminate()
        gone, alive = psutil.wait_procs([proc], timeout=3)
        if alive:
            logger_pid.warning(f"Процесс {pid} проигнорировал SIGTERM. Принудительное уничтожение SIGKILL.")
            proc.kill()
        os.remove(PID_FILE)
    except psutil.NoSuchProcess:
        try:
            os.remove(PID_FILE)
        except:
            pass
    except Exception as e:
        logger_pid.error(f"Критическая ошибка менеджера PID-файлов: {e}", exc_info=True)

def create_pid_file():
    current_pid = os.getpid()
    with open(PID_FILE, 'w', encoding='utf-8') as f:
        f.write(str(current_pid))
    logger_pid.info(f"Регистрация PID-файла успешна. Текущий PID: {current_pid}")

def cleanup():
    if os.path.exists(PID_FILE):
        try:
            os.remove(PID_FILE)
            logger_pid.info("PID-файл успешно удален при выходе из приложения.")
        except Exception as e:
            logger_pid.error(f"Не удалось удалить PID-файл: {e}", exc_info=True)

def main():
    logger_pid.info(f"=== ЗАПУСК ПРИЛОЖЕНИЯ v{APP_VERSION} ===")
    check_and_clean_pid()
    create_pid_file()
    clear_restart_flag()

    try:
        import recorder
        recorder.main()
    except KeyboardInterrupt:
        logger_pid.info("Получен сигнал Ctrl+C, завершение...")
        sys.exit(0)
    except Exception as e:
        logger_pid.critical(f"Необратимый сбой инициализации recorder: {e}", exc_info=True)
        sys.exit(1)
    finally:
        release_single_instance()
        cleanup()
        logger_pid.info("=== СЕССИЯ ЗАКРЫТА ===")
        shutdown_logging()

if __name__ == "__main__":
    main()