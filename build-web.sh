#!/bin/bash
NAME_OF_TAG=$(date "+%Y%m%d%H%M")
IMAGE_NAME=registry-vpc.cn-hangzhou.aliyuncs.com/caihong5g/xiaozhi-web

docker build --no-cache -f Dockerfile-web -t $IMAGE_NAME:$NAME_OF_TAG .
docker tag $IMAGE_NAME:$NAME_OF_TAG $IMAGE_NAME:latest
docker push $IMAGE_NAME:$NAME_OF_TAG
docker push $IMAGE_NAME:latest
