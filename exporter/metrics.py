from prometheus_client import Histogram, Gauge, CollectorRegistry

registry = CollectorRegistry()

TasksByStateGauge = Gauge(
    "celery_tasks", "Number of tasks per state", ["state"], registry=registry
)

TasksByStateAndNameGauge = Gauge(
    "celery_tasks_by_name",
    "Number of tasks per state and name",
    ["state", "name"],
    registry=registry,
)

TaskRuntimeByNameHistogram = Histogram(
    "celery_tasks_runtime_seconds",
    "Task runtime (seconds)",
    ["name"],
    registry=registry,
)

WorkersGauge = Gauge("celery_workers", "Number of alive workers", registry=registry)

TaskLatencyHistogram = Histogram(
    "celery_task_latency",
    "Seconds between a task is received and started.",
    registry=registry,
)

QueueLengthGauge = Gauge(
    "celery_queue_length",
    "Number of tasks in the queue.",
    ["queue_name"],
    registry=registry,
)
