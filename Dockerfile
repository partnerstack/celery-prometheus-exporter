FROM python:3.7-alpine

WORKDIR /app

# Install Pipenv, copy required files and install dependencies
RUN pip install pipenv
COPY Pipfile Pipfile
COPY Pipfile.lock Pipfile.lock
RUN pwd && ls && pipenv install --system
# Copy in application files
COPY . /app
# Set entry point & command to exec script
CMD ["/bin/sh", "/app/docker-entrypoint.sh"]

EXPOSE 8888