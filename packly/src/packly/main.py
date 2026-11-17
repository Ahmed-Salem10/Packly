from fastapi import FastAPI

app = FastAPI()

@app.get("/healthz")
def read_health():
    return {"status": "ok"}