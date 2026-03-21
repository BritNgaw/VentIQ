from flask import Flask, request, jsonify, render_template

app = Flask(__name__)

history = []
MAX_POINTS = 50

# Device settings (interactive)
settings = {
    "HOT_TEMP": 26,
    "COLD_TEMP": 18,
    "ECO_ACTIONS": 0,
    "MONEY_SAVED": 0.0
}

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/data", methods=["POST"])
def receive_data():
    data = request.json
    history.append(data)
    if len(history) > MAX_POINTS:
        history.pop(0)
    return {"status": "ok"}

@app.route("/data", methods=["GET"])
def get_data():
    return jsonify(history)

@app.route("/settings", methods=["GET", "POST"])
def handle_settings():
    global settings
    if request.method == "POST":
        settings.update(request.json)
    return jsonify(settings)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
