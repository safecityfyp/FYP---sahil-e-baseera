# GPU image. Build: docker build -t wrongway . ; Run: see README "Deployment".
FROM nvcr.io/nvidia/pytorch:24.08-py3
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN pip install --no-cache-dir -e .
EXPOSE 8088
ENTRYPOINT ["wrongway"]
CMD ["run", "-c", "/config/system.yaml"]
