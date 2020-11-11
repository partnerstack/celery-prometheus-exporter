from celery import Celery

import time

from app import config

celery_app = Celery()
celery_app.config_from_object(config)


@celery_app.task
def one():
    time.sleep(0.01)


@celery_app.task
def two():
    time.sleep(0.02)


@celery_app.task
def three():
    time.sleep(0.03)


print(celery_app.tasks.keys())
