SHELL = /bin/sh
VERSION := $(shell cat VERSION)

all: image

image:
	docker build -f Dockerfile -t celery_exporter:$(VERSION) -t celery_exporter:latest .

clean:
	rm -rf celery_exporter.img *.egg-info build dist

publish: all
	docker tag celery_exporter partnerstack/celery_exporter:$(VERSION)
	docker push partnerstack/celery_exporter:$(VERSION)
