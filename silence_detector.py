# silence_detector.py
import time
import logging

logger = logging.getLogger(__name__)

class SilenceDetector:
    """
    Детектор тишины на основе уровня громкости.
    Если уровень громкости ниже порога в течение заданного времени,
    вызывается callback-функция (например, для автоматической остановки записи).
    """

    def __init__(self, threshold=5.0, timeout_sec=20.0, callback=None):
        """
        :param threshold: порог громкости в процентах (0-100), ниже которого считается тишиной
        :param timeout_sec: время в секундах непрерывной тишины для срабатывания
        :param callback: функция, вызываемая при срабатывании (без аргументов)
        """
        self.threshold = threshold
        self.timeout_sec = timeout_sec
        self.callback = callback
        self.silence_start = None      # момент начала тишины (None если не в тишине)
        self.is_silent = False
        self._triggered = False        # флаг, что детектор уже сработал

    def update(self, volume):
        """
        Обновляет состояние детектора текущим уровнем громкости.
        volume — значение от 0 до 100 (проценты).
        """
        if self._triggered:
            return  # уже сработал, игнорируем дальнейшие обновления

        now = time.time()

        if volume < self.threshold:
            # Начало тишины
            if self.silence_start is None:
                self.silence_start = now
                self.is_silent = True
                logger.debug(f"Тишина началась в {now:.3f}")
            else:
                # Проверяем, не превышена ли длительность тишины
                silent_duration = now - self.silence_start
                if silent_duration >= self.timeout_sec:
                    logger.info(
                        f"Тишина длится {silent_duration:.1f} сек, достигнут порог {self.timeout_sec} сек. "
                        "Вызов callback для остановки записи."
                    )
                    self._triggered = True
                    if self.callback:
                        self.callback()
        else:
            # Громкость выше порога – тишина прервана
            if self.is_silent:
                logger.debug(f"Тишина прервана, длилась {now - self.silence_start:.1f} сек")
            self.silence_start = None
            self.is_silent = False

    def reset(self):
        """Сбрасывает состояние детектора (например, при старте новой записи)."""
        self.silence_start = None
        self.is_silent = False
        self._triggered = False
        logger.debug("SilenceDetector сброшен")

    def get_silence_duration(self):
        """
        Возвращает текущую длительность непрерывной тишины (в секундах).
        Если тишины нет или детектор уже сработал, возвращает 0.0.
        """
        if self.silence_start is not None and not self._triggered:
            return time.time() - self.silence_start
        return 0.0