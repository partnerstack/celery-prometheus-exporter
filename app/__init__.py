from celery import Celery

import time
import logging
from app import config

celery_app = Celery()
celery_app.config_from_object(config)


@celery_app.task
def one():
    logging.info("ONE")
    time.sleep(0.2)


@celery_app.task
def two():
    logging.info("TWO")
    time.sleep(0.2)


@celery_app.task
def three():
    logging.info("THREE")
    time.sleep(0.2)


print(celery_app.tasks.keys())
