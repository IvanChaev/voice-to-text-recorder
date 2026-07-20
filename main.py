# main.py
import os
import sys
import json
import logging
import psutil
import traceback
from datetime import datetime

# ========== ПРИНУДИТЕЛЬНАЯ УСТАНОВКА ПУТИ К КЭШУ ОТКЛЮЧЕНА ==========
# Если вы хотите изменить папку кэша Hugging Face, установите переменную окружения HF_HOME
# или раскомментируйте строки ниже и укажите свой путь.
# CUSTOM_CACHE = "D:/ProgramData/.cache/huggingface"
# os.environ["HF_HOME"] = CUSTOM_CACHE
# os.environ["TRANSFORMERS_CACHE"] = CUSTOM_CACHE
# os.environ["HUGGINGFACE_HUB_CACHE"] = CUSTOM_CACHE
# ===================================================================

sys.modules.setdefault("main", sys.modules[__name__])

LOG_DIR = "logs"
SESSION_START_TIME = datetime.now()
LOG_FILENAME = os.path.join(LOG_DIR, f"app_{SESSION_START_TIME:%Y-%m-%d_%H-%M-%S}.log")
LOG_LEVEL = "DEBUG"
LOG_KEEP_SESSIONS = 20

from logger_utils import setup_logging, shutdown_logging, log_time, log_exception

setup_logging(LOG_FILENAME, LOG_LEVEL, log_dir=LOG_DIR, keep_sessions=LOG_KEEP_SESSIONS)
logger_pid = logging.getLogger("PIDManager")

# ---------- ДЕФОЛТНЫЕ НАСТРОЙКИ (large-v3-turbo + int8_float16) ----------
DEFAULT_SETTINGS = {
    "model_size": "large-v3-turbo",
    "device": "cuda",               # можно изменить на "cpu" в настройках, если нет видеокарты
    "compute_type": "int8_float16",
    "beam_size": 5,
    "sample_rate": 16000,
    "language": "auto",
    "autostart": False,
    "hotkey": "F3",                 # удобная клавиша по умолчанию
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
        self.logger.info(f"Загрузка Whisper: {model_size} | Устройство: {device} | Вычисления: {compute_type}")
        self.model = WhisperModel(
            model_size_or_path=model_size,
            device=device,
            compute_type=compute_type
        )
        self.beam_size = beam_size

    def transcribe(self, audio_data):
        if audio_data is None or len(audio_data) == 0:
            self.logger.warning("Пустой массив на входе декодера.")
            return "", "unknown", 0.0
        
        segments, info = self.model.transcribe(
            audio_data,
            beam_size=self.beam_size,
            vad_filter=True
        )
        text = " ".join(segment.text for segment in segments)
        return text, info.language, info.language_probability

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
    logger_pid.info("=== ЗАПУСК ПРИЛОЖЕНИЯ ===")
    check_and_clean_pid()
    create_pid_file()

    try:
        import recorder
        recorder.main()
    except Exception as e:
        logger_pid.critical(f"Необратимый сбой инициализации recorder: {e}", exc_info=True)
        sys.exit(1)
    finally:
        cleanup()
        logger_pid.info("=== СЕССИЯ ЗАКРЫТА ===")
        shutdown_logging()

if __name__ == "__main__":
    main()