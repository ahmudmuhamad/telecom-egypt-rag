#!/usr/bin/env bash
set -e

docker exec -it telecom_ollama ollama pull qwen3-embedding:4b
docker exec -it telecom_ollama ollama pull qwen3.5:0.8b
docker exec -it telecom_ollama ollama pull qwen3.5:2b
docker exec -it telecom_ollama ollama pull qwen3:4b
