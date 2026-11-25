Deployment Steps

cd /opt/hmt-watch-tracker/

git pull --ff-only origin main

docker build -t hmt-watch-tracker:latest .

docker stop hmt-watch-tracker

docker rm hmt-watch-tracker

docker run -d   --name hmt-watch-tracker   --restart unless-stopped   -p 80:8000   -v /opt/hmt-watch-tracker/data:/app/data   --env-file /opt/hmt-watch-tracker/.env   hmt-watch-tracker:latest

docker ps