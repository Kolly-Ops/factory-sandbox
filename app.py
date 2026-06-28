from flask import Flask, jsonify

app = Flask(__name__)


@app.route("/pong")
def pong():
    return jsonify({"pong": True})


if __name__ == "__main__":
    app.run()