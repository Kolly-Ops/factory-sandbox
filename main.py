from fastapi import FastAPI

app = FastAPI()


@app.get("/pong")
def pong():
    return {"pong": True}