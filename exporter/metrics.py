from prometheus_client import Histogram, Gauge

TasksByStateGauge = Gauge("celery_tasks", "Number of tasks per state", ["state"])
TasksByStateAndNameGauge = Gauge(
    "celery_tasks_by_name", "Number of tasks per state and name", ["state", "name"]
)
TaskRuntimeByNameHistogram = Histogram(
    "celery_tasks_runtime_seconds",
    "Task runtime (seconds)",
    ["name"],
)
WorkersGauge = Gauge("celery_workers", "Number of alive workers")
TaskLatencyHistogram = Histogram(
    "celery_task_latency",
    "Seconds between a task is received and started.",
)

QueueLengthGauge = Gauge(
    "celery_queue_length", "Number of tasks in the queue.", ["queue_name"]
)