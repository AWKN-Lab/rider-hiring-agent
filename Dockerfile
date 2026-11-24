FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
# pip 源做成**可覆盖**的 build arg（默认仍是官方源，买家侧行为不变）：
# 受限网络/国内环境里构建时可用
#   docker build --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple -t <tag> .
# 否则容器内 pip 会卡在官方源（本机实测：默认源构建 9 分钟无输出）。
ARG PIP_INDEX_URL="https://pypi.org/simple"
COPY requirements.txt .
RUN pip install --no-cache-dir --index-url "${PIP_INDEX_URL}" -r requirements.txt
COPY app ./app
COPY eval ./eval
COPY scripts ./scripts
COPY tests ./tests
EXPOSE 8077 8099
CMD ["uvicorn", "app.fastapi_app:app", "--host", "0.0.0.0", "--port", "8077"]
