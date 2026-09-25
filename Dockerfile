FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml ./
COPY omega_ib ./omega_ib
RUN pip install --no-cache-dir -e .

COPY . .

RUN mkdir -p /app/data

EXPOSE 8000

CMD ["python", "-m", "omega_ib.main"]
