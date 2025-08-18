from fastapi import FastAPI

app = FastAPI()


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
