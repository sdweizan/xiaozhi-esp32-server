#!/bin/bash
NAME_OF_TAG=$(date "+%Y%m%d%H%M")
NAME_OF_IMAGE=registry-vpc.cn-hangzhou.aliyuncs.com/caihong5g/xiaozhi-server

docker build --no-cache -f Dockerfile-server -t $NAME_OF_IMAGE:$NAME_OF_TAG .
docker tag $NAME_OF_IMAGE:$NAME_OF_TAG $NAME_OF_IMAGE:latest
docker push $NAME_OF_IMAGE:$NAME_OF_TAG
docker push $NAME_OF_IMAGE:latest
