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

# ============================================================
# USER SETTINGS
# ============================================================

WIFI_SSID = "SpectrumSetup-FAC9"
WIFI_PASSWORD = "plentybook122"
API_KEY = "f47f8105e498486958154be69d0793cd"

# Fallback location if auto-detect fails
CITY = "Brooklyn"
LAT = None
LON = None

# Comfort thresholds
HOT_TEMP = 26
COLD_TEMP = 18
AIR_QUALITY_LIMIT = 120000
PREDICTION_MULTIPLIER = 3

# Flask server running on laptop
SERVER_URL = "http://192.168.1.188:5000/data"

# Temperature history
temp_history = []
MAX_HISTORY = 5

# ============================================================
# STATE CONSTANTS
# ============================================================

STATE_OPEN_WINDOW = "open_window"
STATE_AIR_STUFFY = "air_stuffy"
STATE_GOOD = "good"
STATE_UNKNOWN = "unknown"

# ============================================================
# WIFI CONNECTION
# ============================================================

print("Connecting to WiFi...")
wifi.radio.connect(WIFI_SSID, WIFI_PASSWORD)
print("Connected to WiFi!")

pool = socketpool.SocketPool(wifi.radio)
requests = adafruit_requests.Session(pool, ssl.create_default_context())

# ============================================================
# AUTO-DETECT LOCATION
# ============================================================

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

        print("Location detected")
        print("City: {}".format(CITY))
        print("Latitude: {}".format(LAT))
        print("Longitude: {}".format(LON))

    except Exception as e:
        print("Location detection failed:", e)
        LAT = None
        LON = None
        print("Using fallback city: {}".format(CITY))


detect_location()

# ============================================================
# SENSOR SETUP
# ============================================================

i2c = busio.I2C(board.SCL, board.SDA)

bme = adafruit_bme680.Adafruit_BME680_I2C(i2c)

lis3dh = adafruit_lis3dh.LIS3DH_I2C(i2c)
lis3dh.range = adafruit_lis3dh.RANGE_4_G

# ============================================================
# SPEAKER
# ============================================================

speaker = board.A0

# ============================================================
# UI / OUTPUT HELPERS
# ============================================================

def recommendation_text(state):
    if state == STATE_OPEN_WINDOW:
        return "Open the window"
    if state == STATE_AIR_STUFFY:
        return "Air quality is poor"
    if state == STATE_GOOD:
        return "Environment is good"
    return "Unknown"

def show_status(indoor_temp, outdoor_temp, humidity, gas, trend, state, city):
    print("\n" + "=" * 44)
    print("           ENVIRONMENT MONITOR")
    print("=" * 44)
    print("City:         {}".format(city))
    print("Indoor Temp:  {:.1f} C".format(indoor_temp))

    if outdoor_temp is None:
        print("Outdoor Temp: unavailable")
    else:
        print("Outdoor Temp: {:.1f} C".format(outdoor_temp))

    print("Humidity:     {:.1f} %".format(humidity))
    print("Gas:          {}".format(gas))
    print("Trend:        {:.2f} C".format(trend))
    print("Advice:       {}".format(recommendation_text(state)))
    print("=" * 44)

# ============================================================
# WEATHER
# ============================================================

def get_outdoor_temp():
    try:
        if LAT is not None and LON is not None:
            weather_url = (
                "https://api.openweathermap.org/data/2.5/weather?lat={}&lon={}&units=metric&appid={}"
                .format(LAT, LON, API_KEY)
            )
        else:
            weather_url = (
                "https://api.openweathermap.org/data/2.5/weather?q={}&units=metric&appid={}"
                .format(CITY, API_KEY)
            )

        response = requests.get(weather_url)
        data = response.json()
        response.close()

        return data["main"]["temp"]

    except Exception as e:
        print("Weather API error:", e)
        return None

# ============================================================
# HISTORY / TREND
# ============================================================

def update_history(temp):
    temp_history.append(temp)
    if len(temp_history) > MAX_HISTORY:
        temp_history.pop(0)

def calculate_trend():
    if len(temp_history) < 2:
        return 0
    return temp_history[-1] - temp_history[-2]

# ============================================================
# ANALYSIS
# ============================================================

def analyze_environment(indoor_temp, outdoor_temp, gas):
    trend = calculate_trend()
    predicted_temp = indoor_temp + trend * PREDICTION_MULTIPLIER

    print("Trend: {:.2f}".format(trend))
    print("Predicted Temp: {:.2f}".format(predicted_temp))

    if outdoor_temp is None:
        return STATE_UNKNOWN, 0

    if predicted_temp > HOT_TEMP and outdoor_temp < indoor_temp:
        strength = min(1.0, (predicted_temp - HOT_TEMP) / 5)
        return STATE_OPEN_WINDOW, strength

    if predicted_temp < COLD_TEMP and outdoor_temp > indoor_temp:
        strength = min(1.0, (COLD_TEMP - predicted_temp) / 5)
        return STATE_OPEN_WINDOW, strength

    if gas < AIR_QUALITY_LIMIT:
        return STATE_AIR_STUFFY, 1

    return STATE_GOOD, 0

# ============================================================
# FEEDBACK
# ============================================================

def feedback(state, strength):
    if state == STATE_OPEN_WINDOW:
        print("Recommendation: Open the window")
        pulse_blue(strength)
        simpleio.tone(speaker, 880, duration=0.2)

    elif state == STATE_AIR_STUFFY:
        print("Recommendation: Air quality is poor")
        set_color(65535, 0, 0)
        simpleio.tone(speaker, 660, duration=0.3)

    elif state == STATE_GOOD:
        print("Recommendation: Environment is good")
        set_color(0, 50000, 0)

    else:
        print("Recommendation: Unknown")
        set_color(40000, 40000, 0)

# ============================================================
# DASHBOARD SEND
# ============================================================

def send_to_dashboard(indoor_temp, outdoor_temp, humidity, gas, state, trend):
    payload = {
        "indoor": indoor_temp,
        "outdoor": outdoor_temp,
        "humidity": humidity,
        "gas": gas,
        "state": state,
        "trend": trend,
        "city": CITY,
        "lat": LAT,
        "lon": LON
    }

    try:
        response = requests.post(SERVER_URL, json=payload)
        response.close()
        print("Data sent to dashboard")
    except Exception as e:
        print("Send error:", e)

# ============================================================
# MAIN LOOP
# ============================================================

last_state = STATE_GOOD
last_strength = 0

while True:
    # 1. Read sensors
    indoor_temp = bme.temperature
    humidity = bme.humidity
    gas = bme.gas
    update_history(indoor_temp)

    # 2. Get outdoor weather
    outdoor_temp = get_outdoor_temp()

    # 3. Analyze environment
    state, strength = analyze_environment(indoor_temp, outdoor_temp, gas)
    trend = calculate_trend()

    # 4. Show readable serial UI
    show_status(indoor_temp, outdoor_temp, humidity, gas, trend, state, CITY)

    # 5. Give user feedback through speaker
    feedback(state, strength)

    # 6. Send to Flask dashboard
    send_to_dashboard(indoor_temp, outdoor_temp, humidity, gas, state, trend)

    # 7. Save last feedback state
    last_state = state
    last_strength = strength

    # 8. Wait before next reading
    time.sleep(30) 
