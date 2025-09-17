# app/logger.py
import logging

class Logger:
    def __init__(self):
        logging.basicConfig(format='[ %(levelname)s ] %(message)s', level=logging.INFO)
        self.logger = logging.getLogger("INAI")

    def info(self, message):
        self.logger.info(message)

    def error(self, message):
        self.logger.error(message)

    def warning(self, message):
        self.logger.warning(message)
