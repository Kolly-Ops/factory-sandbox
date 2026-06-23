from flask import Flask

app = Flask(__name__)


@app.route("/ping2")
def ping2():
    return "pong2", 200


if __name__ == "__main__":
    app.run()