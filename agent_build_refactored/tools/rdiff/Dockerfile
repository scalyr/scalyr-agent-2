FROM ubuntu:22.04

RUN apt update
RUN apt install -y rdiff

ADD ./create_diff.sh /scripts/create_diff.sh
ADD ./restore_from_diff.sh /scripts/restore_from_diff.sh