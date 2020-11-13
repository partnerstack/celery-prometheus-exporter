<!-- omit in toc -->
# celery-prometheus-exporter

celery-prometheus-exporter is a Prometheus exporter for Celery metrics.

Only supports Redis.

Major shoutout to @zerok (Horst Gutmann) for creating this exporter. 

<!-- omit in toc -->
## Table of contents
- [Configuration](#configuration)
- [Output](#output)
- [Developing](#developing)
- [Roadmap](#roadmap)


## Configuration

By default, the exporter will be exposed at `localhost:8888`. If you want it
to use another port, use the `--port` option or the environment variable
`PORT`.

By default, this will expect the broker to be available through
`redis://redis:6379/0`, although you can change using the `BROKER_URL` 
environment variable or the `--broker` option.

Use `--tz` to specify the timezone the Celery app is using. Otherwise the
systems local time will be used.


Use `--queue-list` to specify the list of queues that will have its length
monitored (Automatic Discovery of queues isn't supported right now, see limitations/
caveats. You can use the `QUEUE_LIST` environment variable as well.

If none is given, a single queue with the name `celery` is used as the default. 

Use `--priority-levels` or `PRIORITY_LEVELS=true` to enable priority queues.
Exporter will then look for the standard priority levels for Celery with a Redis broker (0, 3, 6, 9)


## Output
 - `celery_tasks` exposes the number of tasks currently known to the queue
  grouped by `state` (RECEIVED, STARTED, ...).
 - `celery_tasks_by_name` exposes the number of tasks currently known to the queue
  grouped by `name` and `state`.
 - `celery_workers` exposes the number of currently probably alive workers
 - `celery_tasks_runtime_seconds` tracks the number of seconds tasks take
  until completed as histogram.  Buckets are set on a log scale up to 24 hours.



## Developing

Start up the development scenario with
`docker-compose up`


Build the docker image
`make image`


## Roadmap
 - [ ] Make compatible with RabbitMQ
 - [ ] Add latency metric support 