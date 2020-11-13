import time
import os
import sys
import signal
import logging

import argparse
import collections
from typing import List, Dict

from threading import Thread
from queue import Queue

from celery import Celery, Task as CeleryTask
import celery.states
import celery.events
from celery.utils.objects import FallbackContext

from kombu.exceptions import TimeoutError as QueueIsEmptyError
from amqp.exceptions import ChannelError as QueueNotFoundError

from prometheus_client import Histogram, Gauge, start_http_server
from metrics import (
    TasksByStateGauge,
    TasksByStateAndNameGauge,
    TaskRuntimeByNameHistogram,
    WorkersGauge,
    # TaskLatencyHistogram,
    QueueLengthGauge,
    registry,
)

import amqp.exceptions

__VERSION__ = open("VERSION", "r").read().strip()

LOG_FORMAT = "[%(asctime)s] %(name)s:%(levelname)s: %(message)s"

PRIORITY_STEPS = [0, 3, 6, 9]
PRIORITY_SEPARATOR = "\x06\x16"


class CeleryEventReceiverThread(Thread):
    def __init__(self, celery_app: Celery, task_state, event_queue: Queue):
        Thread.__init__(self, daemon=True)
        self.celery_app = celery_app
        self.task_state = task_state
        self.event_queue = event_queue

    def run(self):
        with self.celery_app.connection() as connection:
            receiver = self.celery_app.events.Receiver(
                connection,
                handlers={
                    "*": self.handle_event,
                },
            )
            receiver.capture(limit=None, timeout=None, wakeup=True)

    def handle_event(self, event: Dict[str, str]):
        self.task_state.event(event)
        self.collect_task_metrics(event)
        # sleep so main thread can read new state
        time.sleep(0.0001)

    def collect_task_metrics(self, event):
        task = self.task_state.tasks.get(event.get("uuid"))

        if task is None:
            return

        if task.runtime:
            TaskRuntimeByNameHistogram.labels(name=task.name).observe(task.runtime)

        # TODO: How should we track time spent in queue?
        # if task.sent and task.started:
        #     TaskLatencyHistogram.observe(task.started - task.sent)


class CeleryMetricsCollector:
    def __init__(self, celery_app: Celery, queue_list: List[str], task_state):
        self.celery_app = celery_app
        self.queue_list = queue_list
        self.task_state = task_state

        self.timeout_seconds = 0.5
        self.start_time = time.time()
        self.interval_seconds = 5

    def loop(self):
        with self.celery_app.connection_for_read() as connection:
            while True:
                logging.debug(self.task_state)
                self.collect(connection)
                self.tick_sleep()

    def tick_sleep(self):
        """Sleep for a the remaining time within the interval"""
        interval_seconds = float(self.interval_seconds)
        time.sleep(
            interval_seconds - ((time.time() - self.start_time) % interval_seconds)
        )

    def collect(self, connection):
        # Worker Count
        WorkersGauge.set(
            len(self.celery_app.control.ping(timeout=self.timeout_seconds))
        )

        # Queue Length
        self.collect_queue_length_metrics(connection)

        self.collect_task_metrics()

    def collect_queue_length_metrics(self, connection):
        for queue_name in self.queue_list:
            try:
                length = connection.default_channel.queue_declare(
                    queue=queue_name, passive=True
                ).message_count
            except QueueNotFoundError:
                length = 0

            QueueLengthGauge.labels(sanitize_queue_name(queue_name)).set(length)

    def collect_task_metrics(self):
        state_count = collections.Counter(
            t.state for t in self.task_state.tasks.values()
        )

        for state in state_count.elements():
            TasksByStateGauge.labels(state=state).set(state_count[state])

        # count unready tasks by state and name
        state_name_count = collections.Counter(
            (t.state, t.name) for t in self.task_state.tasks.values() if t.name
        )
        for state_name in state_name_count.elements():
            TasksByStateAndNameGauge.labels(
                state=state_name[0],
                name=state_name[1],
            ).set(state_name_count[state_name])


def add_priority_queues(queue_list):
    return [
        queue_name
        if priority_step == 0
        else f"{queue_name}{PRIORITY_SEPARATOR}{priority_step}"
        for queue_name in queue_list
        for priority_step in PRIORITY_STEPS
    ]


def sanitize_queue_name(queue_name):
    return queue_name.replace(PRIORITY_SEPARATOR, ":")


def initialize_metrics(queue_list: List[str]):
    """
    This initializes the available metrics with default values so that
    even before the first event is received, data can be exposed.
    """
    WorkersGauge.set(0)

    for queue_name in queue_list:
        QueueLengthGauge.labels(sanitize_queue_name(queue_name)).set(0)

    for state in celery.states.ALL_STATES:
        TasksByStateGauge.labels(state=state).set(0)


def shutdown(signum, frame):
    """
    Shutdown is called if the process receives a TERM signal. This way
    we try to prevent an ugly stacktrace being rendered to the user on
    a normal shutdown.
    """
    logging.info("Shutting down")
    sys.exit(0)


def main():
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    BROKER_URL = os.environ.get("BROKER_URL", "redis://redis:6379/0")
    PORT = os.environ.get("PORT", "8888")

    QUEUE_LIST = os.environ.get("QUEUE_LIST", [])
    if len(QUEUE_LIST):
        QUEUE_LIST = [queue_name for queue_name in QUEUE_LIST.split(",")]

    PRIORITY_LEVELS = os.environ.get("PRIORITY_LEVELS", "false").lower() == "true"
    VERBOSE = os.environ.get("VERBOSE", "false").lower() == "true"

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--broker",
        dest="broker",
        default=BROKER_URL,
        help=f"URL to the Celery broker, defaults to redis.",
    )

    parser.add_argument(
        "--port",
        dest="port",
        default=PORT,
        help=f"Port to listen on. Defaults to {PORT}",
    )
    parser.add_argument(
        "--tz", dest="tz", default="UTC", help="Timezone used by the celery app."
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=VERBOSE,
        help="Enable verbose logging, set to 'true' or 'false'",
    )
    parser.add_argument(
        "--queue-list",
        dest="queue_list",
        default=QUEUE_LIST,
        type=str,
        nargs="+",
        help="Queue List. Will be checked for its length.",
    )

    parser.add_argument(
        "--priority-levels",
        action="store_true",
        default=PRIORITY_LEVELS,
        help="Flag if queues should expanded with priority levels",
    )
    parser.add_argument("--version", action="version", version=__VERSION__)

    opts = parser.parse_args()

    if opts.verbose:
        logging.basicConfig(level=logging.DEBUG, format=LOG_FORMAT)
    else:
        logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)

    if opts.tz:
        os.environ["TZ"] = opts.tz
        time.tzset()

    logging.info("Setting up celery for {}".format(opts.broker))

    # default queue list to the default queue name if not given
    queue_list = ["celery"] if len(opts.queue_list) == 0 else opts.queue_list

    # Add priority step queues to queue_list if flag is set true
    queue_list = add_priority_queues(queue_list) if opts.priority_levels else queue_list

    celery_app = Celery(broker=opts.broker, result_backend=opts.broker)

    logging.info(f"Monitoring queues {queue_list}")

    initialize_metrics(queue_list)
    start_http_server(int(opts.port), registry=registry)

    task_state = celery_app.events.State(max_tasks_in_memory=100000)

    event_queue = Queue()

    logging.info("Starting event receiver")
    celery_event_receiver_thread = CeleryEventReceiverThread(
        celery_app, task_state, event_queue
    )
    celery_event_receiver_thread.start()

    logging.info("Listening for new events")

    celery_metrics_collector = CeleryMetricsCollector(
        celery_app, queue_list, task_state=task_state
    )
    celery_metrics_collector.loop()


if __name__ == "__main__":
    main()
