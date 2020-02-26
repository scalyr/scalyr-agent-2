#!/usr/bin/env python
from __future__ import unicode_literals
from __future__ import print_function


fpm_package_builder_dockerfile = """
FROM python:3.6 as fpm_package_builder

RUN apt update && apt install -y ruby ruby-dev rubygems rpm build-essential

RUN gem install --no-document fpm
    """
