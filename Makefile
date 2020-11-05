all: image

image: celery_prometheus_exporter.py Dockerfile requirements/*
	docker build -f Dockerfile -t celery_exporter .

clean:
	rm -rf celery_exporter.img *.egg-info build dist

publish: all
	docker tag celery_exporter partnerstack/celery_exporter:1.3.0
	docker push partnerstack/celery_exporter:1.3.0
