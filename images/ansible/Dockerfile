FROM python:3.9

COPY apt-install.sh /
COPY deblist.txt /
RUN bash apt-install.sh
COPY requirements.txt /
RUN pip install -r requirements.txt
COPY ansible_run.py /
CMD ansible_run.py