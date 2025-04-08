#!/bin/bash
set -e

services=("cleanup" "watcher" "queue" "splitter" "converter" "combiner" "metadata")

for service in "${services[@]}"; do
    echo "===== Building image for $service ====="
    docker build -t nlivestudent/kip-$service:latest -t nlivestudent/kip-$service:v1.0 ./$service
    echo "===== Pushing image for $service ====="
    docker push nlivestudent/kip-$service:latest
    docker push nlivestudent/kip-$service:v1.0
done
