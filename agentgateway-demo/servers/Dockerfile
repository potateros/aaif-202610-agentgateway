FROM python:3.12-slim
# mcp<2: the 2.x SDK renamed exceptions and is not yet what these toy servers target.
RUN pip install --no-cache-dir "mcp<2" "pyjwt[crypto]"
WORKDIR /app
COPY . /app
