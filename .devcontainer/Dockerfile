FROM python:3.9.6-slim-buster

RUN apt-get update \
    && apt-get install -y git build-essential vim procps curl \
    # cleaning up unused files
    && apt-get purge -y --auto-remove -o APT::AutoRemove::RecommendsImportant=false \
    && rm -rf /var/lib/apt/lists/*

COPY requirements_all.txt requirements_test.txt /
RUN pip install --no-cache-dir -U pip \
    && pip install --no-cache-dir -r /requirements_all.txt -r /requirements_test.txt \
    && rm /requirements_all.txt /requirements_test.txt \
    && echo 'export PS1="\[$(tput setaf 6)\]\w \[$(tput setaf 7)\]\\$ \[$(tput sgr0)\]"' >> /root/.bashrc

ENV PYTHONPATH /workspaces/pyunifiprotect/
