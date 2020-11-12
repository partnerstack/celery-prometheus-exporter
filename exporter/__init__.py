from __future__ import print_function
from typing import List, Dict
import argparse
import collections
from itertools import chain
import logging
from prometheus_client import Histogram, Gauge, start_http_server
import signal
import sys
import threading
import time
import os

from celery import Celery
from celery import Task as CeleryTask
import celery.states
import celery.events
from celery.utils.objects import FallbackContext

from kombu.exceptions import TimeoutError as QueueIsEmptyError
from amqp.exceptions import ChannelError as QueueNotFoundError

from metrics import (
    TasksByStateGauge,
    TasksByStateAndNameGauge,
    TaskRuntimeByNameHistogram,
    WorkersGauge,
    TaskLatencyHistogram,
    QueueLengthGauge,
    registry,
)

import amqp.exceptions

__VERSION__ = "1.3.0"

LOG_FORMAT = "[%(asctime)s] %(name)s:%(levelname)s: %(message)s"


def setup_metrics(celery_app: Celery, queue_list: List[str]):
    """
    This initializes the available metrics with default values so that
    even before the first event is received, data can be exposed.
    """

    logging.info("Setting up metrics, trying to connect to broker...")
    WorkersGauge.set(0)

    for queue_name in queue_list:
        QueueLengthGauge.labels(queue_name).set(0)

    for state in celery.states.ALL_STATES:
        TasksByStateGauge.labels(state=state).set(0)


class CeleryMetricsCollector:
    def __init__(self, celery_app: Celery, queue_list: List[str]):
        self.task_state = celery_app.events.State(max_tasks_in_memory=100000)
        self.celery_app = celery_app
        self.queue_list = queue_list
        self.known_states = set()
        self.timeout_seconds = 1

    def run(self):
        # Open a connection
        connection = self.celery_app.connection_for_read()

        # Worker Count
        WorkersGauge.set(
            len(self.celery_app.control.ping(timeout=self.timeout_seconds))
        )

        for queue_name in self.queue_list:
            try:
                length = connection.default_channel.queue_declare(
                    queue=queue_name, passive=True
                ).message_count
            except QueueNotFoundError:
                length = 0

            QueueLengthGauge.labels(queue_name).set(length)

        # MonitorThread(app=celery_app, max_tasks_in_memory=10000)
        recv = self.celery_app.events.Receiver(
            connection,
            handlers={
                "*": self.process_celery_event,
            },
        )

        try:
            recv.capture(limit=None, timeout=self.timeout_seconds, wakeup=True)
        except QueueIsEmptyError:
            logging.debug("Queue is empty")

        # Make sure we release the connection
        connection.release()

    def process_celery_event(self, event: Dict[str, str]):
        # TODO: give event a type, it is simply a dictionary with 'type', 'timestamp' and 'state', perhaps wrap with entity

        if celery.events.group_from(event["type"]) == "task":
            event_state = event["type"].replace("task-", "")
            state = celery.events.state.TASK_EVENT_TO_STATE[event_state]
            event["state"] = state
            if state == celery.states.STARTED:
                self.observe_latency(event)
            self.collect_tasks(event)

    def observe_latency(self, event):
        prev_event = self.task_state.tasks.get(event["uuid"])

        if prev_event is None or prev_event.state == celery.states.RECEIVED:
            return

        TaskLatencyHistogram.observe(
            event["local_received"] - prev_event.local_received
        )

    def collect_tasks(self, event: Dict[str, str]):

        logging.debug(f"collect tasks {event}")

        if event["state"] in celery.states.READY_STATES:
            self.incr_ready_task(event)
        else:
            # add event to list of in-progress tasks
            self.task_state._event(event)

        self.collect_unready_tasks()

    def incr_ready_task(self, event):
        TasksByStateGauge.labels(state=event["state"]).inc()
        # remove event from list of in-progress tasks
        event = self.task_state.tasks.pop(event["uuid"], None)
        if event is None:
            logging.debug("No task found in ready state")
            return

        TasksByStateAndNameGauge.labels(state=event.state, name=event.name).inc()
        if event.runtime:
            TaskRuntimeByNameHistogram.labels(name=event.name).observe(event.runtime)

    def collect_unready_tasks(self):
        state_count = collections.Counter(
            t.state for t in self.task_state.tasks.values()
        )

        for task_state in state_count.elements():
            TasksByStateGauge.labels(state=task_state).set(state_count[task_state])

        # count unready tasks by state and name
        state_name_count = collections.Counter(
            (t.state, t.name) for t in self.task_state.tasks.values() if t.name
        )
        for task_state in state_name_count.elements():
            TasksByStateAndNameGauge.labels(
                state=task_state[0],
                name=task_state[1],
            ).set(state_name_count[task_state])


def tick_sleep(start_time: float, interval_seconds: int = 5):
    """Sleep for a the remaining time within the interval"""
    interval_seconds = float(interval_seconds)
    time.sleep(interval_seconds - ((time.time() - start_time) % interval_seconds))


def shutdown(signum, frame):
    """
    Shutdown is called if the process receives a TERM signal. This way
    we try to prevent an ugly stacktrace being rendered to the user on
    a normal shutdown.
    """
    logging.info("Shutting down")
    sys.exit(0)


def main():
    BROKER_URL = os.environ.get("BROKER_URL", "redis://redis:6379/0")
    PORT = os.environ.get("PORT", "8888")
    QUEUE_LIST = os.environ.get("QUEUE_LIST", [])
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
        nargs="+",
        help="Queue List. Will be checked for its length.",
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

    if opts.queue_list:
        # CLI argument will likely be a string nested in a list
        queue_list = opts.queue_list
        if type(opts.queue_list) == str:
            queue_list = [opts.queue_list]
        if len(queue_list) == 1:
            queue_list = (
                bytearray(queue_list.pop().encode("utf-8"))
                .decode("unicode_escape")
                .split(",")
            )

        # TODO: Split these into priorities
        # This is lazy and needs re-implementing properly
        # just ensuring the queue names look normal in the exporter
        # sanitized_queue_name = (
        #     queue.replace("{", "")
        #     .replace("}", "")
        #     .replace("\x06", "")
        #     .replace("\x16", "")
        # )

    celery_app = Celery(broker=opts.broker)

    logging.info(f"Monitoring queues {queue_list}")

    setup_metrics(celery_app, queue_list=queue_list)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    start_http_server(int(opts.port), registry=registry)
    celery_metrics_collector = CeleryMetricsCollector(celery_app, queue_list)

    start_time = time.time()
    while True:
        logging.debug("Tick")
        celery_metrics_collector.run()
        tick_sleep(start_time, interval_seconds=5)


if __name__ == "__main__":
    main()
