from celery import Celery

import time

from app import config

celery_app = Celery()
celery_app.config_from_object(config)


@celery_app.task
def one():
    time.sleep(2)


@celery_app.task
def two():
    time.sleep(2)


@celery_app.task
def three():
    time.sleep(2)


print(celery_app.tasks.keys())
