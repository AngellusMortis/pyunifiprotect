FROM python:3.10-slim-bullseye

ENV PYTHONUNBUFFERED 1
ENV PYTHONDONTWRITEBYTECODE 1

RUN addgroup --system --gid 1000 python \
    && adduser --system --shell /bin/bash --uid 1000 --ingroup python python

RUN --mount=type=cache,mode=0755,id=apt,target=/var/lib/apt/lists apt-get update -qq \
    && apt-get install -yqq git build-essential vim procps curl jq ffmpeg sudo \
    && echo 'python ALL=(ALL) NOPASSWD: ALL' >> /etc/sudoers \
    && echo 'export PS1="\[$(tput setaf 6)\]\w \[$(tput setaf 7)\]\$ \[$(tput sgr0)\]"' >> /home/python/.bashrc \
    && chown python:python /home/python/.bashrc

COPY requirements.txt /
RUN --mount=type=cache,mode=0755,target=/root/.cache/pip pip install -U pip \
    && pip install -r /requirements.txt \
    && rm /requirements.txt

ENV PYTHONPATH /workspaces/pyunifiprotect/
ENV PATH $PATH:/workspaces/pyunifiprotect/.bin
USER python
WORKDIR /workspaces/pyunifiprotect/
