"""
CONFIGURATION FILE - HARDWARE PINOUT & SETTINGS
PRODUCTION MODE - RASPBERRY PI ONLY
OPTIMIZED FOR PIGPIO LIBRARY
"""

# ============================================================
# DISPLAY SETTINGS
# ============================================================
SCREEN_RESOLUTION = "1024x600"
VIDEO_FOLDER = "/home/pi/videos/"

# ============================================================
# GPIO PIN DEFINITIONS (BCM MODE)
# ============================================================
class PinConfig:
    """
    GPIO Pin Configuration - Safe for Raspberry Pi 3/4/5
    Optimized for pigpio library
    
    ACTIVE LOW for IR Sensors (with internal pull-up):
    - HIGH = idle (no object detected)
    - LOW = triggered (object detected)
    
    Note: pigpio works with all GPIOs, no SPI/I2C conflicts
    """
    
    # ========== LEDs (Outputs) ==========
    LED_1 = 17
    LED_2 = 18
    LED_3 = 27
    LED_4 = 22
    LED_5 = 23
    LED_6 = 24
    
    # ========== Main Motor Relay (Output) ==========
    MAIN_MOTOR_RELAY = 5
    
    # ========== Servo Motors - PIGPIO PWM ==========
    # pigpio supports hardware PWM on any GPIO 0-31
    SERVO_180 = 12   # Works perfectly with pigpio
    SERVO_90 = 13    # Works perfectly with pigpio
    
    # ========== NEMA 17 Stepper Motors (A4988) ==========
    TURN_STEP = 19
    TURN_DIR = 26
    TURN_ENABLE = 8   # Works fine with pigpio
    
    PUSH_STEP = 20
    PUSH_DIR = 21
    PUSH_ENABLE = 9   # Works fine with pigpio
    
    # ========== Control Buttons ==========
    BUTTON_1 = 6 
    BUTTON_2 = 7      # Works fine with pigpio
    
    # ========== IR Sensors (Letter Detection) ==========
    SENSOR_P = 14     # Letter P
    SENSOR_R = 15     # Letter R
    SENSOR_E = 4      # Letter E
    SENSOR_M = 25     # Letter M
    SENSOR_I = 10     # Letter I - Works with pigpio (no SPI conflict)
    SENSOR_O = 11     # Letter O - Works with pigpio (no SPI conflict)
    
    # ========== Special Trigger Sensors ==========
    SENSOR_7 = 16     # Turn motor trigger
    SENSOR_8 = 3      # Push motor trigger - Works with pigpio

# ============================================================
# LED ARRAY
# ============================================================
LED_PINS = [
    PinConfig.LED_1, PinConfig.LED_2, PinConfig.LED_3,
    PinConfig.LED_4, PinConfig.LED_5, PinConfig.LED_6
]

# ============================================================
# SENSOR TO LETTER MAPPING
# ============================================================
SENSOR_LETTER_MAP = {
    PinConfig.SENSOR_P: 'P',
    PinConfig.SENSOR_R: 'R',
    PinConfig.SENSOR_E: 'E',
    PinConfig.SENSOR_M: 'M',
    PinConfig.SENSOR_I: 'I',
    PinConfig.SENSOR_O: 'O'
}

# ============================================================
# TIMING CONFIGURATIONS
# ============================================================

# Debounce times (milliseconds)
# pigpio's glitch filter is more precise, so we can use smaller values
SENSOR_BOUNCE_TIME = 50      # For IR sensors
BUTTON_BOUNCE_TIME = 100     # For physical buttons

# Stepper motor timing (microseconds)
STEP_PULSE_WIDTH_US = 10      # Pulse width for stepper steps
STEP_DELAY_US = 10            # Delay between steps

# ============================================================
# PIGPIO SPECIFIC CONFIGURATIONS
# ============================================================

# pigpio daemon settings
PIGPIO_HOST = 'localhost'     # Can be IP address for remote Pi
PIGPIO_PORT = 8888            # Default pigpio port

# pigpio glitch filter (microseconds)
# More precise than software debounce
PIGPIO_GLITCH_FILTER_US = 50000  # 50ms in microseconds

# pigpio watchdog (milliseconds)
# Automatically detects disconnected sensors
PIGPIO_WATCHDOG_MS = 1000        # Alert if no signal for 1 second

# Servo pulse width ranges (microseconds)
# Standard servo: 500us = 0°, 1500us = 90°, 2500us = 180°
SERVO_PULSE_MIN_US = 500
SERVO_PULSE_MID_US = 1500
SERVO_PULSE_MAX_US = 2500

# Servo movement speed
SERVO_MOVE_DURATION_SEC = 0.5    # Time for smooth servo movement

# ============================================================
# VIDEO FILE NAMES
# ============================================================
VIDEO_ATTRACTION = "Attraction.mp4"
VIDEO_AVAILABLE = "Available.mp4"
VIDEO_GOOD = "Good.mp4"

# ============================================================
# STATE MACHINE TIMINGS
# ============================================================

# ATTRACTION mode timings (seconds)
ATTRACTION_MOTOR_ON_TIME = 120    # Motor ON duration in attraction
ATTRACTION_MOTOR_OFF_TIME = 240   # Motor OFF duration in attraction

# AVAILABLE mode timings (seconds)
AVAILABLE_MOTOR_ON_TIME = 60      # Motor ON duration in available
AVAILABLE_SERVO_90_TIME = 30      # Servo 90° active time

# GOOD mode timings (seconds)
GOOD_MOTOR_ON_TIME = 60           # Motor ON duration in good mode
GOOD_SERVO_180_TIME = 10          # Servo 180° extended time before return
GOOD_SERVO_90_TIME = 60           # Servo 90° active time

# ============================================================
# DEBUG AND LOGGING
# ============================================================

# Enable detailed logging
DEBUG_MODE = True

# Log file path (if None, logs to console only)
LOG_FILE_PATH = None  # "/var/log/interactive_display.log"

# Verbose GPIO events
VERBOSE_GPIO = True   # Print all GPIO state changes

# ============================================================
# SYSTEM CHECKS
# ============================================================

def validate_pin_config():
    """Validate pin configuration for conflicts"""
    all_pins = [
        PinConfig.LED_1, PinConfig.LED_2, PinConfig.LED_3,
        PinConfig.LED_4, PinConfig.LED_5, PinConfig.LED_6,
        PinConfig.MAIN_MOTOR_RELAY,
        PinConfig.SERVO_180, PinConfig.SERVO_90,
        PinConfig.TURN_STEP, PinConfig.TURN_DIR, PinConfig.TURN_ENABLE,
        PinConfig.PUSH_STEP, PinConfig.PUSH_DIR, PinConfig.PUSH_ENABLE,
        PinConfig.BUTTON_1, PinConfig.BUTTON_2,
        PinConfig.SENSOR_P, PinConfig.SENSOR_R, PinConfig.SENSOR_E,
        PinConfig.SENSOR_M, PinConfig.SENSOR_I, PinConfig.SENSOR_O,
        PinConfig.SENSOR_7, PinConfig.SENSOR_8
    ]
    
    # Check for duplicates
    duplicates = [pin for pin in all_pins if all_pins.count(pin) > 1]
    if duplicates:
        print(f"⚠ WARNING: Duplicate pins in configuration: {set(duplicates)}")
        return False
    
    # Check for reserved pins (pigpio specific)
    reserved_pins = [0, 1, 28, 29, 30, 31]  # Some pins are reserved on certain Pis
    conflicts = [pin for pin in all_pins if pin in reserved_pins]
    if conflicts:
        print(f"⚠ WARNING: Reserved pins being used: {conflicts}")
        return False
    
    print("✓ Pin configuration validated")
    return True

# Auto-validate on import
validate_pin_config()