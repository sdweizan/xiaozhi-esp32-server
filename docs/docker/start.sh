#!/bin/bash
# 启动Java后端（docker内监听8003端口）
java -DLOG_HOME=/app/logs -Dspring.profiles.active=prd -jar /app/xiaozhi-esp32-api.jar --server.port=8003 &

# 启动Nginx（前台运行保持容器存活）
nginx -g 'daemon off;'