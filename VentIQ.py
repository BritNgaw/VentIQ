import time
import board
import pwmio
import simpleio
import busio
import wifi
import socketpool
import ssl
import adafruit_requests
import adafruit_bme680
import adafruit_lis3dh

# -----------------------------
# USER SETTINGS
# -----------------------------

WIFI_SSID = "SpectrumSetup-FAC9"
WIFI_PASSWORD = "plentybook122"

API_KEY = "f47f8105e498486958154be69d0793cd"

# Fallback location if auto-detect fails
CITY = "Brooklyn"
LAT = None
LON = None

HOT_TEMP = 26
COLD_TEMP = 18
AIR_QUALITY_LIMIT = 120000

PREDICTION_MULTIPLIER = 3

# Flask server running on laptop
SERVER_URL = "http://192.168.1.122:5000/data"  # Replace with your laptop IP

# temperature history
temp_history = []
MAX_HISTORY = 5

# -----------------------------
# WIFI CONNECTION
# -----------------------------

print("Connecting to WiFi...")
wifi.radio.connect(WIFI_SSID, WIFI_PASSWORD)
print("Connected!")

pool = socketpool.SocketPool(wifi.radio)
requests = adafruit_requests.Session(pool, ssl.create_default_context())

# -----------------------------
# AUTO-DETECT LOCATION
# -----------------------------

def detect_location():
    global LAT, LON, CITY

    try:
        print("Detecting location from IP...")
        response = requests.get("https://ipapi.co/json/")
        data = response.json()
        response.close()

        LAT = data.get("latitude")
        LON = data.get("longitude")

        detected_city = data.get("city")
        if detected_city:
            CITY = detected_city

        print("Detected city:", CITY)
        print("Latitude:", LAT)
        print("Longitude:", LON)

    except Exception as e:
        print("Location detection failed:", e)
        LAT = None
        LON = None
        print("Using fallback city:", CITY)

# Run location detection once after Wi-Fi connects
detect_location()

# -----------------------------
# SENSOR SETUP
# -----------------------------

i2c = busio.I2C(board.SCL, board.SDA)

bme = adafruit_bme680.Adafruit_BME680_I2C(i2c)

lis3dh = adafruit_lis3dh.LIS3DH_I2C(i2c)
lis3dh.range = adafruit_lis3dh.RANGE_4_G

# -----------------------------
# RGB LED SETUP
# -----------------------------

red = pwmio.PWMOut(board.D11)
green = pwmio.PWMOut(board.D12)
blue = pwmio.PWMOut(board.D13)

def set_color(r, g, b):
    red.duty_cycle = r
    green.duty_cycle = g
    blue.duty_cycle = b

# -----------------------------
# LED ANIMATION
# -----------------------------

def pulse_blue(strength):
    brightness = int(20000 + strength * 40000)
    for i in range(0, brightness, 1000):
        set_color(0, 0, i)
        time.sleep(0.01)
    for i in range(brightness, 0, -1000):
        set_color(0, 0, i)
        time.sleep(0.01)

# -----------------------------
# SPEAKER
# -----------------------------

speaker = board.A0

# -----------------------------
# GET OUTDOOR WEATHER
# -----------------------------

def get_outdoor_temp():
    try:
        if LAT is not None and LON is not None:
            weather_url = (
                "https://api.openweathermap.org/data/2.5/weather?lat="
                + str(LAT)
                + "&lon="
                + str(LON)
                + "&units=metric&appid="
                + API_KEY
            )
        else:
            weather_url = (
                "https://api.openweathermap.org/data/2.5/weather?q="
                + CITY
                + "&units=metric&appid="
                + API_KEY
            )

        response = requests.get(weather_url)
        data = response.json()
        response.close()

        outdoor_temp = data["main"]["temp"]
        return outdoor_temp

    except Exception as e:
        print("Weather API error:", e)
        return None

# -----------------------------
# UPDATE TEMPERATURE HISTORY
# -----------------------------

def update_history(temp):
    temp_history.append(temp)
    if len(temp_history) > MAX_HISTORY:
        temp_history.pop(0)

# -----------------------------
# CALCULATE TEMPERATURE TREND
# -----------------------------

def calculate_trend():
    if len(temp_history) < 2:
        return 0
    return temp_history[-1] - temp_history[-2]

# -----------------------------
# SMART PREDICTIVE ALGORITHM
# -----------------------------

def analyze_environment(indoor_temp, outdoor_temp, gas):
    trend = calculate_trend()
    predicted_temp = indoor_temp + trend * PREDICTION_MULTIPLIER

    print("Trend:", trend)
    print("Predicted Temp:", predicted_temp)

    if outdoor_temp is None:
        return "unknown", 0

    if predicted_temp > HOT_TEMP and outdoor_temp < indoor_temp:
        strength = min(1.0, (predicted_temp - HOT_TEMP) / 5)
        return "open_window", strength

    if predicted_temp < COLD_TEMP and outdoor_temp > indoor_temp:
        strength = min(1.0, (COLD_TEMP - predicted_temp) / 5)
        return "open_window", strength

    if gas < AIR_QUALITY_LIMIT:
        return "air_stuffy", 1

    return "good", 0

# -----------------------------
# FEEDBACK SYSTEM
# -----------------------------

def feedback(state, strength):
    if state == "open_window":
        print("Recommendation: Open the window")
        pulse_blue(strength)
        simpleio.tone(speaker, 880, duration=0.2)

    elif state == "air_stuffy":
        print("Air quality poor")
        set_color(65535, 0, 0)
        simpleio.tone(speaker, 660, duration=0.3)

    elif state == "good":
        print("Environment good")
        set_color(0, 50000, 0)

    else:
        set_color(40000, 40000, 0)

# -----------------------------
# TAP DETECTION
# -----------------------------

def tap_detected():
    x, y, z = lis3dh.acceleration
    return abs(x) > 15 or abs(y) > 15 or abs(z) > 15

# -----------------------------
# MAIN LOOP
# -----------------------------

last_state = "good"
last_strength = 0

while True:
    indoor_temp = bme.temperature
    humidity = bme.humidity
    gas = bme.gas

    print("Indoor Temp:", indoor_temp)
    print("Humidity:", humidity)
    print("Gas:", gas)

    update_history(indoor_temp)

    outdoor_temp = get_outdoor_temp()
    print("Outdoor Temp:", outdoor_temp)

    state, strength = analyze_environment(indoor_temp, outdoor_temp, gas)

    feedback(state, strength)

    # -----------------------------
    # SEND DATA TO FLASK DASHBOARD
    # -----------------------------
    payload = {
        "indoor": indoor_temp,
        "outdoor": outdoor_temp,
        "humidity": humidity,
        "gas": gas,
        "state": state,
        "trend": calculate_trend(),
        "city": CITY,
        "lat": LAT,
        "lon": LON
    }

    try:
        requests.post(SERVER_URL, json=payload)
    except Exception as e:
        print("Send error:", e)

    last_state = state
    last_strength = strength

    if tap_detected():
        print("Tap detected - replay recommendation")
        feedback(last_state, last_strength)
        time.sleep(2)

    time.sleep(30)
