from loguru import logger as log
from sys import stderr
log.remove()
log.add(stderr, format='<white>{time:HH:mm:ss}</white>'
                       ' | <level>{level: <8}</level>'
                       ' - <white>{message}</white>')