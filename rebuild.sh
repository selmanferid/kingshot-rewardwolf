#!/bin/bash
cd /home/selman/kingshot
docker stop kingshot-daemon && docker rm kingshot-daemon
docker rmi kingshot-daemon
docker build -t kingshot-daemon .
docker compose up -d daemon
