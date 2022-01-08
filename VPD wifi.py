import time
import board
import busio
from digitalio import DigitalInOut, Direction
import adafruit_dotstar as dotstar
from adafruit_esp32spi import adafruit_esp32spi
from adafruit_esp32spi import adafruit_esp32spi_wifimanager
from adafruit_io.adafruit_io import IO_HTTP, AdafruitIO_RequestError
import adafruit_rgbled
from adafruit_esp32spi import PWMOut
from adafruit_ntp import NTP
import adafruit_sht31d
import math
import gc

print("Imported Libs")

dot = dotstar.DotStar(board.APA102_SCK, board.APA102_MOSI, 1, brightness=0.8)
dot[0] = (25, 25, 25)
ground = DigitalInOut(board.D5)
ground.direction = Direction.OUTPUT
power = DigitalInOut(board.D7)
power.direction = Direction.OUTPUT
ground.value = False
power.value = True
time.sleep(5)

print("DotStar & I2C ground and power set")

# Get wifi details and more from a secrets.py file
try:
    from secrets import secrets
except ImportError:
    print("WiFi secrets are kept in secrets.py, please add them there!")
    raise
print("Added secrets")

# Set ESP32 pins
esp32_cs = DigitalInOut(board.D13)
esp32_reset = DigitalInOut(board.D12)
esp32_ready = DigitalInOut(board.D11)

spi = busio.SPI(board.SCK, board.MOSI, board.MISO)

esp = adafruit_esp32spi.ESP_SPIcontrol(spi, esp32_cs, esp32_ready, esp32_reset)

esp32_cs.value = True

time.sleep(5)
print("WiFi Powerd UP")

RED_LED = PWMOut.PWMOut(esp, 26)
GREEN_LED = PWMOut.PWMOut(esp, 27)
BLUE_LED = PWMOut.PWMOut(esp, 25)
airlift_light = adafruit_rgbled.RGBLED(RED_LED, BLUE_LED, GREEN_LED)

wifi = adafruit_esp32spi_wifimanager.ESPSPI_WiFiManager(esp, secrets, dot)

# Setup Sensor
i2c = board.I2C()

sensor = adafruit_sht31d.SHT31D(i2c)
sensor.frequency = adafruit_sht31d.FREQUENCY_1
sensor.mode = adafruit_sht31d.MODE_PERIODIC
sensor.heater = True
time.sleep(1)
sensor.heater = False
print("Sensor Heater OK")

# Setup Adafruit IO
io = IO_HTTP(secrets["aio_username"], secrets["aio_key"], wifi)

print("i2c, SPI, In Out Made")

try:
    # Get the 'digital' feed from Adafruit IO
    digital_feed = io.get_feed("led-dot")
except AdafruitIO_RequestError:
    # If no 'digital' feed exists, create one
    digital_feed = io.create_new_feed("led-dot")
try:
    # get time from wifi
    ntp = NTP(esp)
    ntp.set_time()
    start_time = time.time()
except (ValueError, RuntimeError) as e:
    print("Failed to set time\n", e)
    wifi.reset()
esp32_cs.value = False
print("wifi tested")

# calculate current Vapour-pressure deficit
def vpd(temp, rh):
    # Estimated Saturation Pressures
    # Saturation Vapor Pressure method 1
    es1 = 0.6108 * math.exp(17.27 * temp / (temp + 237.3))
    # Saturation Vapor Pressure method 2
    es2 = 6.11 * 10 ** ((7.5 * temp) / (237.3 + temp)) / 10
    # Saturation Vapor Pressure method 3
    es3 = 6.112 * math.exp(17.62 * temp / (temp + 243.12)) / 10
    # Saturation Vapor Pressure mean
    es = (es1 + es2 + es3) / 3
    # actual partial pressure of water vapor in air
    ea = rh / 100 * es
    # return Vapour-pressure deficit
    vpd = es - ea
    return vpd


def newvpd(temp, rh):
    # Saturation Vapor Pressure *Arden Buck equation(1996)*
    if temp > 0:
        es = 0.61121 * math.exp((18.678 - (temp / 234.5)) * (temp / (257.14 + temp)))
    else:
        es = 0.61115 * math.exp((23.036 - temp / 333.7) * (temp / (279.82 + temp)))
    if rh > 20 and rh < 80:
        # actual partial pressure of water vapor in air
        ea = rh / 100 * es
        # return Vapour-pressure deficit
        VPD = es - ea
        return VPD
    else:
        vpd(temp, rh)


def heatindexlow(temp, hum):
    # Convert celius to fahrenheit (heat-index is only fahrenheit compatible)
    fahrenheit = (temp * 9 / 5) + 32

    # Creating multiples of 'fahrenheit' & 'hum' values for the coefficients
    T2 = math.pow(fahrenheit, 2)
    T3 = math.pow(fahrenheit, 3)
    H2 = math.pow(hum, 2)
    H3 = math.pow(hum, 3)

    # Coefficients for the calculations
    C1 = [
        -42.379,
        2.04901523,
        10.14333127,
        -0.22475541,
        -6.83783e-03,
        -5.481717e-02,
        1.22874e-03,
        8.5282e-04,
        -1.99e-06,
    ]
    C2 = [
        0.363445176,
        0.988622465,
        4.777114035,
        -0.114037667,
        -0.000850208,
        -0.020716198,
        0.000687678,
        0.000274954,
        0,
    ]
    C3 = [
        16.923,
        0.185212,
        5.37941,
        -0.100254,
        0.00941695,
        0.00728898,
        0.000345372,
        -0.000814971,
        0.0000102102,
        -0.000038646,
        0.0000291583,
        0.00000142721,
        0.000000197483,
        -0.0000000218429,
        0.000000000843296,
        -0.0000000000481975,
    ]

    # Calculating heat-indexes with 3 different formula
    heatindex1 = (
        C1[0]
        + (C1[1] * fahrenheit)
        + (C1[2] * hum)
        + (C1[3] * fahrenheit * hum)
        + (C1[4] * T2)
        + (C1[5] * H2)
        + (C1[6] * T2 * hum)
        + (C1[7] * fahrenheit * H2)
        + (C1[8] * T2 * H2)
    )
    heatindex2 = (
        C2[0]
        + (C2[1] * fahrenheit)
        + (C2[2] * hum)
        + (C2[3] * fahrenheit * hum)
        + (C2[4] * T2)
        + (C2[5] * H2)
        + (C2[6] * T2 * hum)
        + (C2[7] * fahrenheit * H2)
        + (C2[8] * T2 * H2)
    )
    heatindex3 = (
        C3[0]
        + (C3[1] * fahrenheit)
        + (C3[2] * hum)
        + (C3[3] * fahrenheit * hum)
        + (C3[4] * T2)
        + (C3[5] * H2)
        + (C3[6] * T2 * hum)
        + (C3[7] * fahrenheit * H2)
        + (C3[8] * T2 * H2)
        + (C3[9] * T3)
        + (C3[10] * H3)
        + (C3[11] * T3 * hum)
        + (C3[12] * fahrenheit * H3)
        + (C3[13] * T3 * H2)
        + (C3[14] * T2 * H3)
        + (C3[15] * T3 * H3)
    )

    feelslike = (heatindex1 + heatindex2 + heatindex3) / 3
    return feelslike


# Send data with ESP32 over wifi to adafruit io
def sendsens(feed, whatz):
    try:
        esp32_cs.value = True
        print("Posting", feed, "...", end="")
        data = whatz
        payload = {"value": data}
        time.sleep(3)
        response = wifi.post(
            "https://io.adafruit.com/api/v2/"
            + secrets["aio_username"]
            + "/feeds/"
            + feed
            + "/data",
            json=payload,
            headers={"X-AIO-KEY": secrets["aio_key"]},
        )
        print(response.json())
        response.close()
        esp32_cs.value = False
        print("POST OK , Sleep for 50 sec")
        time.sleep(50)
    except (ValueError, RuntimeError) as e:
        print("Failed to get data, retrying\n", e)
        wifi.reset()
    response = None


# convert seconds to time
def secondsToText(secs):
    days = secs // 86400
    hours = (secs - days * 86400) // 3600
    minutes = (secs - days * 86400 - hours * 3600) // 60
    seconds = secs - days * 86400 - hours * 3600 - minutes * 60
    result = (
        ("{0} day{1}, ".format(days, "s" if days != 1 else "") if days else "")
        + ("{0} hour{1}, ".format(hours, "s" if hours != 1 else "") if hours else "")
        + (
            "{0} minute{1}, ".format(minutes, "s" if minutes != 1 else "")
            if minutes
            else ""
        )
        + (
            "{0} second{1} ".format(seconds, "s" if seconds != 1 else "")
            if seconds
            else ""
        )
    )
    return result


gc.collect()
print(gc.mem_free())

while True:
    current_time = time.time()
    ran_time = current_time - start_time
    print("Program running for: {}".format(secondsToText(ran_time)))
    currenttemp = min(sensor.temperature)
    time.sleep(10)
    currentrd = max(sensor.relative_humidity)
    print("\nTemp: ", str(round((currenttemp * 1.8 + 32), 1)), "F")
    print("Humidity: %0.1f %%" % currentrd)
    print("VPD: ", newvpd(currenttemp, currentrd))
    # For Feels Like Temp
    T = round((currenttemp * 1.8 + 32), 1)
    RH = round((currentrd), 1)
    if T >= 76:
        feelslike = heatindexlow(currenttemp, currentrd)
        print("feelslike high: ", feelslike)
    elif T < 76 and T > 50:
        feelslike = T
    else:
        feelslike = round(
            (
                (
                    13.12
                    + 0.6215 * currenttemp
                    - 11.37 * math.pow(3, 0.16)
                    + 0.3965 * currenttemp * math.pow(3, 0.16)
                )
                * 1.8
                + 32
            )
        )
    # Get data from 'digital' feed for color of LED
    print("getting data from IO...")
    try:
        feed_data = io.receive_data(digital_feed["key"])
        color = feed_data["value"]
        print("AIO color =", color)
        airlift_light.color = tuple(int(color[z : z + 2], 16) for z in (1, 3, 5))
    except (ValueError, RuntimeError) as e:
        print("Failed to get data, retrying\n", e)
        wifi.reset()
    time.sleep(50)
    # Send data to Adafruit IO
    sendsens("vpd", (vpd(currenttemp, currentrd)))
    sendsens("humidity", currentrd)
    sendsens("temp", (currenttemp * 1.8 + 32))
    sendsens("hi", feelslike)
    # update time
    esp32_cs.value = True
    try:
        ntp = NTP(esp)
        ntp.set_time()
    except (ValueError, RuntimeError) as e:
        print("Failed to set time\n", e)
        wifi.reset()
    esp32_cs.value = False
    # keep memory clean
    print(gc.mem_free())
    gc.collect()
