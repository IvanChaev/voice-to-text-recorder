# logger_utils.py
import os
import sys
import time
import glob
import shutil
import logging
import logging.handlers
import functools
import traceback
import queue
from datetime import datetime
import psutil

# Активируем поддержку ANSI-последовательностей (цветов) в стандартной консоли Windows (cmd)
if sys.platform == "win32":
    os.system("")

    # Приложение запускается через pythonw.exe, у которого нет своей консоли.
    # Если какая-то библиотека (например, pyrubberband, дергающий внешний
    # rubberband.exe для time-stretch) запускает дочерний процесс через
    # subprocess без явного подавления окна, Windows на мгновение показывает
    # для него новое окно консоли — это и есть то самое "мерцание".
    # Патчим subprocess.Popen глобально на уровне процесса, чтобы ЛЮБОЙ
    # дочерний процесс (текущий и будущие) запускался без создания окна
    # консоли, независимо от того, что вызвало Popen.
    import subprocess as _subprocess
    _original_popen_init = _subprocess.Popen.__init__

    def _no_console_popen_init(self, *args, **kwargs):
        creationflags = kwargs.get("creationflags", 0)
        kwargs["creationflags"] = creationflags | _subprocess.CREATE_NO_WINDOW
        return _original_popen_init(self, *args, **kwargs)

    _subprocess.Popen.__init__ = _no_console_popen_init

# Попытка импортировать GPU-мониторинг
try:
    import pynvml
    pynvml.nvmlInit()
    GPU_AVAILABLE = True
except Exception:
    GPU_AVAILABLE = False
    pynvml = None

# Цветовые коды ANSI для красивого вывода в консоль
class ANSIColors:
    RESET = "\033[0m"
    DEBUG = "\033[36m"     # Циановый
    INFO = "\033[32m"      # Зеленый
    WARNING = "\033[33m"   # Желтый
    ERROR = "\033[31m"     # Красный
    CRITICAL = "\033[41m\033[37m" # Белый на красном фоне

class ColorFormatter(logging.Formatter):
    """Кастомный форматизатор для консоли с цветовой индикацией уровней логирования."""
    def format(self, record):
        level_color = getattr(ANSIColors, record.levelname, ANSIColors.RESET)
        # Сохраняем оригинальные поля, чтобы не испортить их для других обработчиков
        orig_levelname = record.levelname
        orig_msg = record.msg
        
        # Подсвечиваем имя уровня
        record.levelname = f"{level_color}{record.levelname:<8}{ANSIColors.RESET}"
        
        # Если это ошибка, подсвечиваем само сообщение красным
        if record.levelno >= logging.ERROR:
            record.msg = f"{ANSIColors.ERROR}{record.msg}{ANSIColors.RESET}"
            
        result = super().format(record)
        
        # Восстанавливаем оригинальные значения
        record.levelname = orig_levelname
        record.msg = orig_msg
        return result

_listener = None

def move_short_logs(log_dir, pattern="app_*.log", shorts_subdir="shorts",
                     min_size_bytes=10 * 1024, min_lines=100, exclude_filename=None):
    """
    Переносит логи прошлых сессий, которые весят меньше min_size_bytes
    ИЛИ содержат меньше min_lines строк, в подпапку log_dir/shorts_subdir.
    "Мелкие" логи обычно означают, что программа завершилась почти сразу
    после запуска (например, ошибка инициализации) — их удобнее держать
    отдельно от полноценных сессий.
    """
    try:
        files = glob.glob(os.path.join(log_dir, pattern))
        if not files:
            return
        shorts_dir = os.path.join(log_dir, shorts_subdir)
        for f in files:
            if exclude_filename and os.path.abspath(f) == os.path.abspath(exclude_filename):
                continue  # не трогаем файл лога текущей сессии
            try:
                is_small = os.path.getsize(f) < min_size_bytes
                if not is_small:
                    with open(f, 'r', encoding='utf-8', errors='ignore') as fh:
                        line_count = sum(1 for _ in fh)
                    is_small = line_count < min_lines

                if is_small:
                    os.makedirs(shorts_dir, exist_ok=True)
                    shutil.move(f, os.path.join(shorts_dir, os.path.basename(f)))
            except OSError:
                pass
    except Exception:
        pass  # Перемещение коротких логов не должно мешать запуску приложения

def cleanup_old_logs(log_dir, pattern="app_*.log", keep_sessions=20):
    """Удаляет старые файлы логов прошлых сессий, оставляя keep_sessions самых свежих."""
    try:
        files = glob.glob(os.path.join(log_dir, pattern))
        if len(files) <= keep_sessions:
            return
        files.sort(key=os.path.getmtime)  # от самых старых к самым новым
        for old_file in files[:-keep_sessions]:
            try:
                os.remove(old_file)
            except OSError:
                pass
    except Exception:
        pass  # Очистка старых логов не должна мешать запуску приложения

def setup_logging(log_filename, log_level_str="DEBUG", log_dir=None, keep_sessions=20):
    """
    Инициализирует централизованную асинхронную систему логирования.
    Все логгеры пишут в потокобезопасную очередь, которая обрабатывается в фоне.

    Каждый запуск программы пишет в СВОЙ файл (имя файла должно быть уникальным
    для сессии, например с меткой времени) — так логи разных сессий никогда
    не перемешиваются, и не нужно листать один гигантский/ротированный файл
    в поисках нужной ошибки.
    """
    global _listener
    if _listener is not None:
        return  # Уже настроено

    level = getattr(logging, log_level_str.upper(), logging.DEBUG)
    resolved_log_dir = log_dir or os.path.dirname(log_filename)
    if resolved_log_dir and not os.path.exists(resolved_log_dir):
        os.makedirs(resolved_log_dir, exist_ok=True)

    # Переносим "мелкие" логи прошлых сессий (< 10 КБ или < 100 строк) в logs/shorts,
    # чтобы они не засоряли основную папку и не мешали искать полноценные сессии
    if resolved_log_dir:
        move_short_logs(resolved_log_dir, exclude_filename=log_filename)

    # Подчищаем логи старых сессий, чтобы папка logs/ не росла бесконечно
    if resolved_log_dir:
        cleanup_old_logs(resolved_log_dir, keep_sessions=keep_sessions)

    # 1. Создаем общую очередь для логов
    log_queue = queue.Queue(-1)
    
    # 2. Форматы логов
    # Подробный формат для файла (с потоками, файлами кода и микросекундами)
    file_format = logging.Formatter(
        '%(asctime)s.%(msecs)03d | [%(threadName)s] | %(levelname)-8s | %(name)s.%(funcName)s:%(lineno)d - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    # Формат для консоли (чуть компактнее, но информативный)
    console_format = ColorFormatter(
        '%(asctime)s.%(msecs)03d | %(levelname)s | %(name)s:%(lineno)d - %(message)s',
        datefmt='%H:%M:%S'
    )

    # 3. Настройка обработчиков (Handlers), которые будут работать в фоновом потоке слушателя
    # Файл сессии не ротируется по размеру: у каждого запуска программы уже
    # свой уникальный файл (см. LOG_FILENAME в main.py), поэтому используем
    # обычный FileHandler, а не RotatingFileHandler.
    file_handler = logging.FileHandler(log_filename, encoding='utf-8')
    file_handler.setFormatter(file_format)
    file_handler.setLevel(level)

    # Консольный обработчик
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(console_format)
    console_handler.setLevel(level)

    # 4. Запуск QueueListener в отдельном демоническом потоке
    _listener = logging.handlers.QueueListener(log_queue, file_handler, console_handler, respect_handler_level=True)
    _listener.start()

    # 5. Настраиваем корневой логгер на отправку всех записей в очередь через QueueHandler
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers.clear()
    
    queue_handler = logging.handlers.QueueHandler(log_queue)
    root_logger.addHandler(queue_handler)

    # Глушим избыточный низкоуровневый спам от COM-интерфейсов Windows (SAPI/comtypes)
    logging.getLogger("comtypes").setLevel(logging.WARNING)
    
    # Отключаем пошаговую отладку импорта плагинов Pillow (PIL)
    logging.getLogger("PIL").setLevel(logging.WARNING)
    
    # Снижаем детальность логов сетевой библиотеки httpx/httpcore до уровня INFO
    logging.getLogger("httpcore").setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.INFO)

    # Перенаправляем неперехваченные исключения интерпретатора в логгер
    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logging.getLogger("sys.unhandled").critical(
            "Необработанное исключение уровня системы!", 
            exc_info=(exc_type, exc_value, exc_traceback)
        )

    sys.excepthook = handle_exception
    logging.getLogger(__name__).info(f"Асинхронная система логирования успешно инициализирована. Файл сессии: {log_filename}")

def shutdown_logging():
    """Корректно останавливает фоновый поток записи логов и сбрасывает буферы."""
    global _listener
    if _listener is not None:
        logging.getLogger(__name__).info("Завершение работы системы логирования...")
        _listener.stop()
        _listener = None

def get_system_info():
    """Собирает неблокирующие метрики производительности системы."""
    info = {
        "timestamp": datetime.now().isoformat(),
        "cpu_percent": psutil.cpu_percent(interval=None),
        "cpu_count": psutil.cpu_count(),
        "memory": {
            "total": psutil.virtual_memory().total,
            "available": psutil.virtual_memory().available,
            "used": psutil.virtual_memory().used,
            "percent": psutil.virtual_memory().percent
        },
        "disk_usage": {
            "total": psutil.disk_usage('/').total,
            "used": psutil.disk_usage('/').used,
            "free": psutil.disk_usage('/').free,
            "percent": psutil.disk_usage('/').percent
        }
    }
    if GPU_AVAILABLE and pynvml is not None:
        try:
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            info["gpu"] = {
                "memory_total": mem_info.total,
                "memory_used": mem_info.used,
                "memory_free": mem_info.free,
                "memory_percent": (mem_info.used / mem_info.total) * 100,
                "temperature": pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
            }
        except Exception:
            info["gpu"] = "Error reading GPU telemetry"
    return info

def log_system_state(context=""):
    """Логирует текущее аппаратное состояние в структурированном виде."""
    try:
        info = get_system_info()
        gpu_str = ""
        if GPU_AVAILABLE and 'gpu' in info and isinstance(info['gpu'], dict):
            gpu_str = (f" | GPU VRAM: {info['gpu']['memory_percent']:.1f}% "
                       f"({info['gpu']['memory_used']/1024**3:.2f}/{info['gpu']['memory_total']/1024**3:.2f} GB) "
                       f"Temp: {info['gpu']['temperature']}°C")
        
        logging.getLogger("Telemetry").info(
            f"[{context}] CPU: {info['cpu_percent']}% | "
            f"RAM: {info['memory']['percent']}% ({info['memory']['used']/1024**3:.2f}/{info['memory']['total']/1024**3:.2f} GB)"
            f"{gpu_str}"
        )
    except Exception as e:
        logging.getLogger("Telemetry").warning(f"Не удалось собрать телеметрию: {e}")

def log_time(func):
    """Декоратор для замера времени выполнения функции с подробным выводом аргументов."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        logger = logging.getLogger(func.__module__)
        func_name = func.__name__
        logger.debug(f"Вызов '{func_name}' | args: {args}, kwargs: {kwargs}")
        start_time = time.perf_counter()
        try:
            result = func(*args, **kwargs)
            elapsed = time.perf_counter() - start_time
            logger.info(f"Успешное выполнение '{func_name}' | Время: {elapsed:.4f} сек")
            return result
        except Exception as e:
            elapsed = time.perf_counter() - start_time
            logger.error(f"Сбой в '{func_name}' после {elapsed:.4f} сек! Исключение: {e}", exc_info=True)
            raise
    return wrapper

def log_exception(e):
    """Удобная обертка для детальной записи исключений."""
    logging.getLogger("ExceptionTracker").error(f"Зарегистрировано исключение: {e}", exc_info=True)