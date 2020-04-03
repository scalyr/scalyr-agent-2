FROM python:3.6 as fpm_package_build

RUN apt update && apt install -y ruby ruby-dev rubygems rpm build-essential

RUN gem install --no-document fpm