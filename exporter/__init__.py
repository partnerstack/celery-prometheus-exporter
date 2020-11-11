from __future__ import print_function
from typing import List
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
import celery.states
import celery.events
from celery.utils.objects import FallbackContext

from metrics import (
    TasksByStateGauge,
    TasksByStateAndNameGauge,
    TaskRuntimeByNameHistogram,
    WorkersGauge,
    TaskLatencyHistogram,
    QueueLengthGauge,
)

import amqp.exceptions

__VERSION__ = "1.3.0"

LOG_FORMAT = "[%(asctime)s] %(name)s:%(levelname)s: %(message)s"


class MonitorThread(threading.Thread):
    """
    MonitorThread is the thread that will collect the data that is later
    exposed from Celery using its eventing system.
    """

    def __init__(self, app=None, max_tasks_in_memory=None):
        self._app = app
        self.log = logging.getLogger("monitor")
        self.log.info("Setting up monitor...")
        self._state = self._app.events.State(max_tasks_in_memory=max_tasks_in_memory)
        self._known_states = set()
        self._known_states_names = set()
        self._tasks_started = dict()
        super(MonitorThread, self).__init__()

    def run(self):
        self._monitor()

    def _process_event(self, evt):
        # Events might come in in parallel. Celery already has a lock
        # that deals with this exact situation so we'll use that for now.
        with self._state._mutex:
            if celery.events.group_from(evt["type"]) == "task":
                evt_state = evt["type"][5:]
                state = celery.events.state.TASK_EVENT_TO_STATE[evt_state]

                if state == celery.states.STARTED:
                    self._observe_latency(evt)
                self._collect_tasks(evt, state)

    def _observe_latency(self, evt):
        try:
            prev_evt = self._state.tasks[evt["uuid"]]
        except KeyError:
            pass
        else:
            # ignore latency if it is a retry
            if prev_evt.state == celery.states.RECEIVED:
                TaskLatencyHistogram.observe(
                    evt["local_received"] - prev_evt.local_received
                )

    def _collect_tasks(self, evt, state):
        if state in celery.states.READY_STATES:
            self._incr_ready_task(evt, state)
        else:
            # add event to list of in-progress tasks
            self._state._event(evt)
        self._collect_unready_tasks()

    def _incr_ready_task(self, evt, state):
        TasksByStateGauge.labels(state=state).inc()
        try:
            # remove event from list of in-progress tasks
            event = self._state.tasks.pop(evt["uuid"])
            TasksByStateAndNameGauge.labels(state=state, name=event.name).inc()
            if "runtime" in evt:
                TaskRuntimeByNameHistogram.labels(name=event.name).observe(
                    evt["runtime"]
                )
        except (KeyError, AttributeError):
            pass

    def _collect_unready_tasks(self):
        # count unready tasks by state
        cnt = collections.Counter(t.state for t in self._state.tasks.values())
        self._known_states.update(cnt.elements())
        for task_state in self._known_states:
            TasksByStateGauge.labels(state=task_state).set(cnt[task_state])

        # count unready tasks by state and name
        cnt = collections.Counter(
            (t.state, t.name) for t in self._state.tasks.values() if t.name
        )
        self._known_states_names.update(cnt.elements())
        for task_state in self._known_states_names:
            TasksByStateAndNameGauge.labels(
                state=task_state[0],
                name=task_state[1],
            ).set(cnt[task_state])

    def _monitor(self):
        while True:
            try:
                self.log.info("Connecting to broker...")
                with self._app.connection() as conn:
                    recv = self._app.events.Receiver(
                        conn,
                        handlers={
                            "*": self._process_event,
                        },
                    )
                    setup_metrics(self._app)
                    recv.capture(limit=None, timeout=None, wakeup=True)
                    self.log.info("Connected to broker")
            except Exception:
                self.log.exception("Queue connection failed")
                setup_metrics(self._app)
                time.sleep(5)


class WorkerMonitoringThread(threading.Thread):
    celery_ping_timeout_seconds = 5
    periodicity_seconds = 5

    def __init__(self, app=None, *args, **kwargs):
        self._app = app
        self.log = logging.getLogger("workers-monitor")
        super(WorkerMonitoringThread, self).__init__(*args, **kwargs)

    def run(self):
        while True:
            self.update_workers_count()
            time.sleep(self.periodicity_seconds)

    def update_workers_count(self):
        try:
            WorkersGauge.set(
                len(self._app.control.ping(timeout=self.celery_ping_timeout_seconds))
            )
        except Exception:
            self.log.exception("Error while pinging workers")


class QueueLengthMonitoringThread(threading.Thread):
    periodicity_seconds = 30

    def __init__(self, app: Celery, queue_list: List[str]):
        self.celery_app = app
        self.queue_list = queue_list
        self.connection = self.celery_app.connection_or_acquire()

        if isinstance(self.connection, FallbackContext):
            self.connection = self.connection.fallback()

        super(QueueLengthMonitoringThread, self).__init__()

    def measure_queues_length(self):
        for queue in self.queue_list:
            length = self.connection.default_channel.queue_declare(
                queue=queue, passive=True
            ).message_count

            self.set_queue_length(queue, length)

    def set_queue_length(self, queue_name, length):
        QueueLengthGauge.labels(queue_name).set(length)

    def run(self):
        while True:
            self.measure_queues_length()
            time.sleep(self.periodicity_seconds)


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


def collect_metrics(celery_app: Celery, queue_list: List[str]):
    # TODO: Port metric collection from all the Threaded classes into here
    # MonitorThread(app=celery_app, max_tasks_in_memory=10000)

    # WorkerMonitoringThread(app=celery_app)

    # QueueLengthMonitoringThread(app=celery_app, queue_list=queue_list)
    pass


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
    DEFAULT_BROKER = os.environ.get("BROKER_URL", "redis://redis:6379/0")
    DEFAULT_PORT = os.environ.get("DEFAULT_ADDR", "8888")
    DEFAULT_MAX_TASKS_IN_MEMORY = int(
        os.environ.get("DEFAULT_MAX_TASKS_IN_MEMORY", "10000")
    )

    DEFAULT_QUEUE_LIST = os.environ.get("QUEUE_LIST", [])
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--broker",
        dest="broker",
        default=DEFAULT_BROKER,
        help=f"URL to the Celery broker, defaults to redis.",
    )

    parser.add_argument(
        "--port",
        dest="port",
        default=DEFAULT_PORT,
        help=f"Port to listen on. Defaults to {DEFAULT_PORT}",
    )
    parser.add_argument(
        "--tz", dest="tz", default="UTC", help="Timezone used by the celery app."
    )
    parser.add_argument(
        "--verbose", action="store_true", default=False, help="Enable verbose logging"
    )
    parser.add_argument(
        "--queue-list",
        dest="queue_list",
        default=DEFAULT_QUEUE_LIST,
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

    start_http_server(int(opts.port))

    start_time = time.time()
    while True:
        print("tick")
        collect_metrics(
            celery_app,
            queue_list,
        )
        tick_sleep(start_time, interval_seconds=5)


if __name__ == "__main__":
    main()
