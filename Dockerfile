FROM python:3.7-slim

RUN mkdir /upgrade_ucs
RUN mkdir /upgrade_ucs/logs

COPY ./upgrade_ucs.py /upgrade_ucs/
COPY ./metadata /upgrade_ucs/
COPY ./requirements.txt /upgrade_ucs/

RUN pip install -r /upgrade_ucs/requirements.txt

WORKDIR /upgrade_ucs

ENTRYPOINT ["./upgrade_ucs.py"]
