FROM python:3.12-slim
WORKDIR /corecoder
COPY pyproject.toml README_CN.md ./
COPY corecoder ./corecoder
RUN pip install --no-cache-dir -e ".[dev]"
ENTRYPOINT ["corecoder"]
