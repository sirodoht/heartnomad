FROM python:3.11
ENV PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1

RUN apt-get update -qq && \
    apt-get install -yq \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r /app/requirements.txt

WORKDIR /app
COPY . /app/
RUN /app/manage.py collectstatic --noinput
