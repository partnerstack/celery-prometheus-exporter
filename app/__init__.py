from celery import Celery

import time
import logging
from app import config

celery_app = Celery()
celery_app.config_from_object(config)


TASK_PRIORITY_HIGH = 9
TASK_PRIORITY_MEDIUM = 4
TASK_PRIORITY_LOW = 0


@celery_app.task(name="app.one.low", priority=TASK_PRIORITY_LOW)
def one_low():
    time.sleep(config.task_sleep_time)


@celery_app.task(name="app.one.medium", priority=TASK_PRIORITY_MEDIUM)
def one_medium():
    time.sleep(config.task_sleep_time)


@celery_app.task(name="app.one.high", priority=TASK_PRIORITY_HIGH)
def one_high():
    time.sleep(config.task_sleep_time)


@celery_app.task(name="app.two.low", priority=TASK_PRIORITY_LOW)
def two_low():
    time.sleep(config.task_sleep_time)


@celery_app.task(name="app.two.medium", priority=TASK_PRIORITY_MEDIUM)
def two_medium():
    time.sleep(config.task_sleep_time)


@celery_app.task(name="app.two.high", priority=TASK_PRIORITY_HIGH)
def two_high():
    time.sleep(config.task_sleep_time)


@celery_app.task(name="app.three.low", priority=TASK_PRIORITY_LOW)
def three_low():
    time.sleep(config.task_sleep_time)


@celery_app.task(name="app.three.medium", priority=TASK_PRIORITY_MEDIUM)
def three_medium():
    time.sleep(config.task_sleep_time)


@celery_app.task(name="app.three.high", priority=TASK_PRIORITY_HIGH)
def three_high():
    time.sleep(config.task_sleep_time)
