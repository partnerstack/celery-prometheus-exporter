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

task_routes = {
    "app.one.*": {"queue": Q1},
    "app.two.*": {"queue": Q2},
    "app.three.*": {"queue": Q3},
}

# how long do each of these schedule tasks sleep for
task_sleep_time = 0.01  # 10ms
schedule_frequency = timedelta(milliseconds=10)  # 9 x 10ms = 900/s, requires

beat_schedule = {
    f"{task_name}.{priority}": {
        "task": f"app.{task_name}.{priority}",
        "schedule": schedule_frequency,
    }
    for task_name in ["one", "two", "three"]
    for priority in ["high", "medium", "low"]
}