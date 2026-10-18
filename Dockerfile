FROM python:3.12-slim
WORKDIR /app
COPY server.py deploy.py ./
COPY static ./static
RUN useradd --create-home --uid 10001 promedics && mkdir /data && chown promedics:promedics /data && chmod -R a+rX /app
USER promedics
ENV PROMEDICS_DB=/data/promedics.sqlite3
EXPOSE 8000
CMD ["python3", "deploy.py"]
