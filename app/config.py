import os
from datetime import timedelta
from kombu import Queue, Exchange

broker_url = os.getenv("BROKER_URL", "redis://redis:6379/0")
result_backend = broker_url
accept_content = ["json", "pickle"]
result_serializer = "pickle"
result_expires = 3600
timezone = "UTC"
task_always_eager = False
task_soft_time_limit = 600
worker_send_task_events = True

Q1 = "queue1"
Q2 = "queue2"
Q3 = "queue3"

task_default_queue = Q1

task_routes = {
    "app.one": {"queue": Q1},
    "app.two": {"queue": Q2},
    "app.three": {"queue": Q3},
}


beat_schedule = {
    "one": {
        "task": "app.one",
        "schedule": timedelta(milliseconds=100),
    },
    "two": {
        "task": "app.two",
        "schedule": timedelta(milliseconds=100),
    },
    "three": {
        "task": "app.three",
        "schedule": timedelta(milliseconds=100),
    },
}