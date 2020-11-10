FROM python:3.7-alpine

WORKDIR /app

# Install Pipenv, copy required files and install dependencies
RUN pip install pipenv
COPY Pipfile Pipfile
# COPY Pipfile.lock Pipfile.lock
RUN pwd && ls
RUN pipenv install
# Copy in application files
COPY . /app
# Set entry point & command to exec script
ENTRYPOINT ["/bin/sh", "/app/docker-entrypoint.sh"]
CMD []
EXPOSE 8888