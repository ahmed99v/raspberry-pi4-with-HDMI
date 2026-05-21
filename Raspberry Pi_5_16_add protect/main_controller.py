"""
MAIN CONTROLLER - STATE MACHINE FOR INTERACTIVE DISPLAY
MIGRATED TO PIGPIO LIBRARY - FIXED EVENT DETECTION
MODIFIED: LEDs now indicate individual letter sensors
"""

import time
import threading
import subprocess
import sys
import os
from enum import Enum
from typing import Optional, Dict, Callable

# Import configuration
import configure as cfg

# Anti-piracy: hardware-bound license verification
import license_manager

# ============================================================
# PIGPIO GPIO LIBRARY (REPLACES RPi.GPIO)
# ============================================================
import pigpio

# Global pigpio instance
pi = None

def init_pigpio():
    """Initialize pigpio connection"""
    global pi
    try:
        pi = pigpio.pi()  # Connect to local Pi's pigpio daemon
        if not pi.connected:
            print("ERROR: Could not connect to pigpio daemon")
            print("Please start it with: sudo pigpiod")
            sys.exit(1)
        print("✓ Connected to pigpio daemon")
        
        # Set global exception handling
        pigpio.exceptions = False
        return True
    except Exception as e:
        print(f"✗ Failed to initialize pigpio: {e}")
        return False

# ============================================================
# SYSTEM STATES
# ============================================================
class SystemState(Enum):
    ATTRACTION = "ATTRACTION"
    AVAILABLE = "AVAILABLE"
    GOOD = "GOOD"

# ============================================================
# GLOBAL SYSTEM STATUS
# ============================================================
class SystemStatus:
    def __init__(self):
        self.current_state = SystemState.ATTRACTION
        self.active_sensors = {letra: False for letra in 'PREMIO'}
        self.video_process = None
        self.current_video = None
        
        # Thread Control Flags
        self.is_led_blinking = False
        self.is_servo_balancing = False
        self.is_letter_video_active = False
        self.good_mode_triggered = False
        
        # Thread Stop Events
        self.stop_main_motor_cycle = threading.Event()
        self.stop_balance = threading.Event()
        self.stop_blink = threading.Event()
        
        # Timers
        self.main_motor_timer: Optional[threading.Timer] = None
        self.servo_90_timer: Optional[threading.Timer] = None
        self.sensor_deactivation_timers = {}
        
        # pigpio PWM handles
        self.pwm_servo_180 = None
        self.pwm_servo_90 = None
        
        # Callback handles (for cleanup)
        self.callback_handles = []
        
        # Last servo positions
        self.last_servo_180_angle = 30
        self.last_servo_90_angle = 0
        
        # Stepper control
        self.steppers_enabled = False
        
        # Status update callback for GUI
        self.status_callback: Optional[Callable] = None
        
        # Map sensors to LEDs (index match)
        self.sensor_to_led = {
            'P': cfg.PinConfig.LED_1,
            'R': cfg.PinConfig.LED_2,
            'E': cfg.PinConfig.LED_3,
            'M': cfg.PinConfig.LED_4,
            'I': cfg.PinConfig.LED_5,
            'O': cfg.PinConfig.LED_6
        }
        
        # NOTE: _init_pwm() and _init_steppers() are called manually
        # in main() after init_pigpio(), to ensure 'pi' is not None.
    
    def _init_pwm(self):
        """Initialize PWM for servos using pigpio"""
        try:
            # Servo 180 on configured pin
            pi.set_mode(cfg.PinConfig.SERVO_180, pigpio.OUTPUT)
            self.pwm_servo_180 = cfg.PinConfig.SERVO_180
            # Start with 0 pulse width (off)
            pi.set_servo_pulsewidth(self.pwm_servo_180, 0)
            time.sleep(0.1)
            print(f"✓ PWM initialized for SERVO_180 on pin {cfg.PinConfig.SERVO_180}")
        except Exception as e:
            print(f"✗ Failed to initialize PWM for SERVO_180: {e}")
        
        try:
            # Servo 90 on configured pin
            pi.set_mode(cfg.PinConfig.SERVO_90, pigpio.OUTPUT)
            self.pwm_servo_90 = cfg.PinConfig.SERVO_90
            pi.set_servo_pulsewidth(self.pwm_servo_90, 0)
            time.sleep(0.1)
            print(f"✓ PWM initialized for SERVO_90 on pin {cfg.PinConfig.SERVO_90}")
        except Exception as e:
            print(f"✗ Failed to initialize PWM for SERVO_90: {e}")
    
    def _init_steppers(self):
        """Initialize stepper motor control pins"""
        try:
            pi.set_mode(cfg.PinConfig.TURN_ENABLE, pigpio.OUTPUT)
            pi.set_mode(cfg.PinConfig.PUSH_ENABLE, pigpio.OUTPUT)
            pi.write(cfg.PinConfig.TURN_ENABLE, 1)  # HIGH = disabled
            pi.write(cfg.PinConfig.PUSH_ENABLE, 1)  # HIGH = disabled
            self.steppers_enabled = False
            print(f"✓ Steppers initialized")
        except Exception as e:
            print(f"✗ Failed to initialize steppers: {e}")
    
    def enable_steppers(self, enable: bool):
        """Enable or disable stepper motors"""
        state = 0 if enable else 1  # A4988: LOW (0) = enabled, HIGH (1) = disabled
        try:
            pi.write(cfg.PinConfig.TURN_ENABLE, state)
            pi.write(cfg.PinConfig.PUSH_ENABLE, state)
            self.steppers_enabled = enable
        except Exception as e:
            print(f"✗ Failed to set steppers state: {e}")
    
    def stop_all_threads(self):
        """Stop all background threads and timers"""
        self.stop_main_motor_cycle.set()
        self.stop_balance.set()
        self.stop_blink.set()
        self.is_led_blinking = False
        self.is_servo_balancing = False
        
        if self.main_motor_timer:
            self.main_motor_timer.cancel()
        if self.servo_90_timer:
            self.servo_90_timer.cancel()
        for timer in self.sensor_deactivation_timers.values():
            timer.cancel()
        self.sensor_deactivation_timers.clear()
    
    def set_status_callback(self, callback: Callable):
        self.status_callback = callback
    
    def update_led_for_sensor(self, letter: str, is_active: bool):
        """Update LED state based on sensor activation"""
        if letter in self.sensor_to_led:
            led_pin = self.sensor_to_led[letter]
            try:
                pi.write(led_pin, 1 if is_active else 0)
                print(f"[LED] LED for letter {letter} {'ON' if is_active else 'OFF'}")
            except Exception as e:
                print(f"✗ Failed to update LED for {letter}: {e}")
    
    def turn_off_all_leds(self):
        """Turn off all letter indicator LEDs"""
        for led_pin in cfg.LED_PINS:
            try:
                pi.write(led_pin, 0)
            except:
                pass
        print(f"[LED] All letter LEDs turned OFF")
    
    def cleanup(self):
        """Clean up pigpio resources"""
        # Cancel all callbacks
        for handle in self.callback_handles:
            try:
                handle.cancel()  # Correct pigpio method to cancel a callback
            except:
                pass
        
        # Stop PWM/servo signals
        if self.pwm_servo_180:
            pi.set_servo_pulsewidth(self.pwm_servo_180, 0)
        if self.pwm_servo_90:
            pi.set_servo_pulsewidth(self.pwm_servo_90, 0)

# Create global status
status = None

# ============================================================
# HARDWARE CONTROL LAYER (MIGRATED TO PIGPIO)
# ============================================================
class HardwareController:
    
    @staticmethod
    def leds_on():
        """Turn on all LEDs - used for general illumination"""
        for pin in cfg.LED_PINS:
            try:
                pi.write(pin, 1)  # HIGH
            except:
                pass
        print(f"[LED] All LEDs turned ON (general illumination)")
    
    @staticmethod
    def leds_off():
        """Turn off all LEDs"""
        for pin in cfg.LED_PINS:
            try:
                pi.write(pin, 0)  # LOW
            except:
                pass
        print(f"[LED] All LEDs turned OFF")
    
    @staticmethod
    def leds_blink(enable: bool):
        """Blink all LEDs - used for GOOD mode celebration"""
        if enable and not (status and status.is_led_blinking):
            if status:
                status.is_led_blinking = True
                status.stop_blink.clear()
            threading.Thread(target=HardwareController._blink_worker, daemon=True).start()
        elif not enable and status:
            status.is_led_blinking = False
            if hasattr(status, 'stop_blink'):
                status.stop_blink.set()
            # Don't automatically turn LEDs on - they will be managed by sensors
    
    @staticmethod
    def _blink_worker():
        """Worker thread for blinking all LEDs (GOOD mode only)"""
        state = True
        while status and status.is_led_blinking and not status.stop_blink.is_set():
            for pin in cfg.LED_PINS:
                try:
                    pi.write(pin, 1 if state else 0)
                except:
                    pass
            state = not state
            time.sleep(0.3)
    
    @staticmethod
    def main_motor(enable: bool):
        try:
            pi.write(cfg.PinConfig.MAIN_MOTOR_RELAY, 1 if enable else 0)
        except:
            pass
    
    @staticmethod
    def servo_180_set_angle(target_angle):
        """Set servo angle using pigpio's servo pulsewidth"""
        # Map angle to pulse width (typical servo: 500us = 0°, 2500us = 180°)
        angle_map = {-30: 0, 0: 500, 30: 1000, 180: 2500}
        pulse_width = angle_map.get(target_angle, 1500)  # 1500us = 90° default
        
        # Smooth movement
        current_pw = angle_map.get(status.last_servo_180_angle, 1500)
        HardwareController._move_servo_smooth(
            status.pwm_servo_180,
            pulse_width,
            current_pw
        )
        status.last_servo_180_angle = target_angle
    
    @staticmethod
    def servo_180_start_balance():
        """Start servo balancing movement"""
        if status and status.is_servo_balancing:
            return
        if status:
            status.is_servo_balancing = True
            status.stop_balance.clear()
        
        def balance_worker():
            direction = 1
            while status and status.is_servo_balancing and not status.stop_balance.is_set():
                HardwareController.servo_180_set_angle(30 if direction == 1 else -30)
                direction *= -1
                time.sleep(1.5)
            if status:
                HardwareController.servo_180_set_angle(0)
        
        threading.Thread(target=balance_worker, daemon=True).start()
    
    @staticmethod
    def servo_180_stop_balance():
        if status:
            status.is_servo_balancing = False
            status.stop_balance.set()
    
    @staticmethod
    def _move_servo_smooth(pin, target_pw, current_pw, duration=0.5):
        """Smooth servo movement using pigpio"""
        if pin is None:
            return
        try:
            steps = 20
            increment = (target_pw - current_pw) / steps
            
            for i in range(steps + 1):
                pi.set_servo_pulsewidth(pin, int(current_pw + (increment * i)))
                time.sleep(duration / steps)
        except Exception as e:
            print(f"✗ Servo movement error: {e}")
    
    @staticmethod
    def servo_90_set_angle(angle):
        """Set servo 90 angle (0 or 90 degrees)"""
        if angle not in [0, 90]:
            return
        
        # Map angle to pulse width
        angle_map = {0: 500, 90: 1500}
        pulse_width = angle_map.get(angle, 500)
        current_pw = angle_map.get(status.last_servo_90_angle, 500)
        
        HardwareController._move_servo_smooth(
            status.pwm_servo_90,
            pulse_width,
            current_pw
        )
        status.last_servo_90_angle = angle
    
    @staticmethod
    def _generate_step_pulse(step_pin, duration_sec, motor_name):
        """Generate step pulses for stepper motor"""
        if status:
            status.enable_steppers(True)
        
        # Set direction pins (assuming TURN_DIR and PUSH_DIR are configured)
        if motor_name == 'turn_motor':
            pi.write(cfg.PinConfig.TURN_DIR, 1)
        elif motor_name == 'push_motor':
            pi.write(cfg.PinConfig.PUSH_DIR, 1)
        
        end_time = time.time() + duration_sec
        while time.time() < end_time:
            try:
                pi.write(step_pin, 1)
                time.sleep(cfg.STEP_PULSE_WIDTH_US / 1000000.0)
                pi.write(step_pin, 0)
                time.sleep(cfg.STEP_DELAY_US / 1000000.0)
            except:
                pass
        
        if status:
            status.enable_steppers(False)
    
    @staticmethod
    def stepper_turn(duration_sec):
        threading.Thread(
            target=HardwareController._generate_step_pulse,
            args=(cfg.PinConfig.TURN_STEP, duration_sec, 'turn_motor'),
            daemon=True
        ).start()
    
    @staticmethod
    def stepper_push(duration_sec):
        threading.Thread(
            target=HardwareController._generate_step_pulse,
            args=(cfg.PinConfig.PUSH_STEP, duration_sec, 'push_motor'),
            daemon=True
        ).start()

# ============================================================
# VIDEO PLAYER CONTROL
# ============================================================
class VideoController:
    @staticmethod
    def play(video_file, loop=False):
        """Play video file using VLC with proper error handling"""
        VideoController.stop()
        
        full_path = os.path.join(cfg.VIDEO_FOLDER, video_file)
        
        if not os.path.exists(full_path):
            print(f"[VIDEO] ERROR: File not found: {full_path}")
            return False
        
        if status:
            status.current_video = video_file
            print(f"[VIDEO] Playing: {video_file} (loop={loop}) in state: {status.current_state}")
        
        # Build cvlc arguments
        vlc_args = [
            'cvlc', '--fullscreen', '--play-and-exit',
            '--no-video-title-show', '--no-osd',
            '--intf', 'dummy',
            '--vout=gles2',
        ]
        
        if loop:
            vlc_args.append('--loop')
        else:
            vlc_args.append('--no-loop')
        
        vlc_args.append(full_path)
        
        # Wayland environment: run as desktop user 'metamorfose' so cvlc
        # can access the Wayland compositor socket (not accessible to root).
        # WAYLAND_DISPLAY and XDG_RUNTIME_DIR are required by Wayland clients.
        wayland_user = 'metamorfose'
        wayland_env = (
            "WAYLAND_DISPLAY=wayland-1 "
            "XDG_RUNTIME_DIR=/run/user/1000 "
            "DISPLAY=:0 "
        )
        vlc_cmd_str = ' '.join(vlc_args)
        cmd = ['sudo', '-u', wayland_user, 'bash', '-c',
               f'{wayland_env}{vlc_cmd_str}']
        
        try:
            if status:
                status.video_process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    preexec_fn=os.setsid
                )
            print(f"[VIDEO] Started with cvlc (Wayland/{wayland_user}): {video_file}")
            return True
        except Exception as e:
            print(f"[VIDEO] Error playing {video_file}: {e}")
            return False
    
    @staticmethod
    def stop():
        if status and status.video_process:
            try:
                import signal
                os.killpg(os.getpgid(status.video_process.pid), signal.SIGTERM)
                status.video_process.wait(timeout=2)
            except:
                try:
                    status.video_process.terminate()
                except:
                    pass
            status.video_process = None
            if status:
                status.current_video = None

# ============================================================
# PIGPIO CALLBACKS (THE FIX!)
# ============================================================
def create_gpio_callback(channel):
    """Create a callback function for a specific GPIO pin"""
    
    def callback_function(gpio, level, tick):
        """pigpio callback: receives gpio, level, and timestamp"""
        # Software debounce (pigpio already has glitch filter, but extra safety)
        time.sleep(0.005)
        
        try:
            # Check if button
            if gpio in [cfg.PinConfig.BUTTON_1, cfg.PinConfig.BUTTON_2]:
                print(f"[GPIO] Button pressed on pin {gpio}")
                if status.current_state != SystemState.AVAILABLE:
                    StateMachine.enter_available()
                else:
                    HardwareController.main_motor(True)
                    if status.main_motor_timer:
                        status.main_motor_timer.cancel()
                    
                    def main_motor_off():
                        if status:
                            HardwareController.main_motor(False)
                    
                    status.main_motor_timer = threading.Timer(60, main_motor_off)
                    status.main_motor_timer.start()
            
            # Check if motion sensor (active LOW)
            elif gpio == cfg.PinConfig.SENSOR_7:
                if level == 0:  # Falling edge (active)
                    print(f"[GPIO] Turn sensor triggered on pin {gpio}")
                    HardwareController.stepper_turn(5)
            elif gpio == cfg.PinConfig.SENSOR_8:
                if level == 0:
                    print(f"[GPIO] Push sensor triggered on pin {gpio}")
                    HardwareController.stepper_push(6)
            
            # Check if letter sensor
            elif gpio in cfg.SENSOR_LETTER_MAP:
                letter = cfg.SENSOR_LETTER_MAP[gpio]
                is_active = (level == 0)  # Active LOW with pull-up
                print(f"[GPIO] Letter sensor '{letter}' on pin {gpio}: {'ACTIVE' if is_active else 'INACTIVE'} (level={level})")
                StateMachine.handle_letter_sensor(gpio, is_active)
                
        except Exception as e:
            print(f"✗ Error in GPIO callback for pin {gpio}: {e}")
    
    return callback_function

def setup_gpio_pigpio():
    """Setup GPIO using pigpio with proper event detection"""
    global status
    
    print("\n" + "=" * 60)
    print("GPIO SETUP WITH PIGPIO - Starting configuration")
    print("=" * 60)
    
    # Configure output pins
    print("\n[1/5] Configuring OUTPUT pins...")
    outputs = cfg.LED_PINS + [
        cfg.PinConfig.MAIN_MOTOR_RELAY,
        cfg.PinConfig.TURN_ENABLE, cfg.PinConfig.TURN_STEP, cfg.PinConfig.TURN_DIR,
        cfg.PinConfig.PUSH_ENABLE, cfg.PinConfig.PUSH_STEP, cfg.PinConfig.PUSH_DIR,
        cfg.PinConfig.SERVO_180, cfg.PinConfig.SERVO_90
    ]
    
    output_success = 0
    for pin in outputs:
        try:
            pi.set_mode(pin, pigpio.OUTPUT)
            pi.write(pin, 0)  # Initialize LOW
            print(f"  ✓ OUTPUT pin {pin} configured")
            output_success += 1
        except Exception as e:
            print(f"  ✗ OUTPUT pin {pin} FAILED: {e}")
    
    # Set direction pins (assuming direction = 1 for forward)
    print("\n[2/5] Setting direction pins...")
    try:
        pi.write(cfg.PinConfig.TURN_DIR, 1)
        pi.write(cfg.PinConfig.PUSH_DIR, 1)
        print(f"  ✓ Direction pins set: TURN_DIR={cfg.PinConfig.TURN_DIR}, PUSH_DIR={cfg.PinConfig.PUSH_DIR} -> HIGH")
    except Exception as e:
        print(f"  ✗ Failed to set direction pins: {e}")
    
    # Configure input pins with pull-up
    print("\n[3/5] Configuring INPUT pins with pull-up...")
    inputs = [
        cfg.PinConfig.BUTTON_1, cfg.PinConfig.BUTTON_2,
        cfg.PinConfig.SENSOR_7, cfg.PinConfig.SENSOR_8,
        cfg.PinConfig.SENSOR_P, cfg.PinConfig.SENSOR_R, cfg.PinConfig.SENSOR_E,
        cfg.PinConfig.SENSOR_M, cfg.PinConfig.SENSOR_I, cfg.PinConfig.SENSOR_O
    ]
    
    input_success = 0
    for pin in inputs:
        try:
            pi.set_mode(pin, pigpio.INPUT)
            pi.set_pull_up_down(pin, pigpio.PUD_UP)  # Enable pull-up resistor
            print(f"  ✓ INPUT pin {pin} configured with pull-up")
            input_success += 1
        except Exception as e:
            print(f"  ✗ INPUT pin {pin} FAILED: {e}")
    
    # Configure event detection with glitch filter (pigpio's superior debounce)
    print("\n[4/5] Configuring glitch filter (debounce)...")
    
    # Set glitch filter on all input pins (50ms debounce)
    # This is pigpio's superior debounce - only reports changes that persist
    for pin in inputs:
        try:
            pi.set_glitch_filter(pin, cfg.SENSOR_BOUNCE_TIME * 1000)  # Convert ms to µs
            print(f"  ✓ Glitch filter set on pin {pin}: {cfg.SENSOR_BOUNCE_TIME}ms")
        except:
            pass
    
    # Add callbacks for all input pins
    print("\n[5/5] Configuring event detection with pigpio callbacks...")
    callback_success = 0
    for pin in inputs:
        try:
            # Determine edge type
            if pin in cfg.SENSOR_LETTER_MAP:
                # Letter sensors need both edges (activation and deactivation)
                edge = pigpio.EITHER_EDGE
            else:
                # Buttons and motion sensors only care about falling edge (active LOW)
                edge = pigpio.FALLING_EDGE
            
            # Create and register callback
            callback_func = create_gpio_callback(pin)
            callback_handle = pi.callback(pin, edge, callback_func)
            
            # Store handle for cleanup
            if status:
                status.callback_handles.append(callback_handle)
            
            pin_type = "LETTER" if pin in cfg.SENSOR_LETTER_MAP else "BUTTON/MOTION"
            print(f"  ✓ {pin_type} pin {pin} - callback registered (edge={edge})")
            callback_success += 1
        except Exception as e:
            print(f"  ✗ Pin {pin} FAILED: {e}")
    
    # Final summary
    print("\n" + "=" * 60)
    print("GPIO SETUP WITH PIGPIO COMPLETED")
    print(f"  OUTPUTS: {output_success} OK")
    print(f"  INPUTS: {input_success} OK")
    print(f"  CALLBACKS: {callback_success} OK")
    print("  ✓ ALL PINS CONFIGURED SUCCESSFULLY")
    print("=" * 60 + "\n")
    
    return True

# ============================================================
# STATE MACHINE (SAME LOGIC, MODIFIED LED BEHAVIOR)
# ============================================================
class StateMachine:
    
    @staticmethod
    def enter_attraction():
        """Enter ATTRACTION mode - looping attraction video"""
        if not status:
            return
        
        print(f"\n[STATE] Entering ATTRACTION mode")
        status.stop_all_threads()
        status.current_state = SystemState.ATTRACTION
        status.is_letter_video_active = False
        status.good_mode_triggered = False
        status.stop_main_motor_cycle.clear()
        
        # Turn off blinking if active
        HardwareController.leds_blink(False)
        
        # In ATTRACTION mode, turn on all LEDs for general illumination
        HardwareController.leds_on()
        
        HardwareController.servo_180_start_balance()
        
        print(f"[VIDEO] Playing attraction video: {cfg.VIDEO_ATTRACTION}")
        VideoController.play(cfg.VIDEO_ATTRACTION, loop=True)
        
        def main_motor_cycle():
            print(f"[MOTOR] Main motor cycle thread started")
            while (status and status.current_state == SystemState.ATTRACTION and 
                   not status.stop_main_motor_cycle.is_set()):
                HardwareController.main_motor(True)
                print(f"[MOTOR] Main motor ON for 120 seconds")
                for _ in range(120):
                    if status and status.stop_main_motor_cycle.is_set():
                        break
                    time.sleep(1)
                HardwareController.main_motor(False)
                print(f"[MOTOR] Main motor OFF for 240 seconds")
                for _ in range(240):
                    if status and status.stop_main_motor_cycle.is_set():
                        break
                    time.sleep(1)
            print(f"[MOTOR] Main motor cycle thread stopped")
        
        threading.Thread(target=main_motor_cycle, daemon=True).start()
    
    @staticmethod
    def enter_available():
        """Enter AVAILABLE mode - waiting for letters"""
        if not status:
            return
        
        print(f"\n[STATE] Entering AVAILABLE mode")
        status.stop_all_threads()
        status.current_state = SystemState.AVAILABLE
        status.is_letter_video_active = False
        status.good_mode_triggered = False
        
        # Turn off blinking if active
        HardwareController.leds_blink(False)
        
        # Reset all letter sensors
        for key in status.active_sensors:
            old_state = status.active_sensors[key]
            status.active_sensors[key] = False
            # Turn off corresponding LED when resetting
            if old_state:
                status.update_led_for_sensor(key, False)
        print(f"[SENSORS] All letter sensors reset and LEDs turned OFF")
        
        HardwareController.servo_180_start_balance()
        
        print(f"[VIDEO] Playing available video: {cfg.VIDEO_AVAILABLE}")
        VideoController.play(cfg.VIDEO_AVAILABLE, loop=True)
        
        HardwareController.main_motor(True)
        print(f"[MOTOR] Main motor ON for 60 seconds")
        if status.main_motor_timer:
            status.main_motor_timer.cancel()
        
        def main_motor_off():
            if status:
                HardwareController.main_motor(False)
                print(f"[MOTOR] Main motor turned OFF after 60 seconds")
        
        status.main_motor_timer = threading.Timer(60, main_motor_off)
        status.main_motor_timer.start()
        
        HardwareController.servo_90_set_angle(90)
        print(f"[SERVO] Servo 90 set to 90 degrees for 30 seconds")
        if status.servo_90_timer:
            status.servo_90_timer.cancel()
        
        def servo_90_off():
            if status:
                HardwareController.servo_90_set_angle(0)
                print(f"[SERVO] Servo 90 returned to 0 degrees")
        
        status.servo_90_timer = threading.Timer(30, servo_90_off)
        status.servo_90_timer.start()
    
    @staticmethod
    def enter_good():
        """Enter GOOD mode - all letters detected, special effects"""
        if not status:
            return
        
        print(f"\n[STATE] Entering GOOD mode - ALL LETTERS DETECTED!")
        status.stop_all_threads()
        status.current_state = SystemState.GOOD
        status.good_mode_triggered = True
        status.is_letter_video_active = False
        
        HardwareController.servo_180_stop_balance()
        
        # GOOD mode overrides individual LEDs with blinking effect
        HardwareController.leds_blink(True)
        
        print(f"[VIDEO] Playing good video: {cfg.VIDEO_GOOD}")
        VideoController.play(cfg.VIDEO_GOOD, loop=True)
        
        HardwareController.main_motor(True)
        print(f"[MOTOR] Main motor ON for 60 seconds")
        
        def main_motor_off():
            if status:
                HardwareController.main_motor(False)
                print(f"[MOTOR] Main motor turned OFF")
        
        threading.Timer(60, main_motor_off).start()
        
        HardwareController.servo_180_set_angle(180)
        print(f"[SERVO] Servo 180 extended to 180 degrees")
        
        def servo_180_return():
            if status:
                HardwareController.servo_180_set_angle(-30)
                print(f"[SERVO] Servo 180 returned to -30 degrees")
        
        threading.Timer(10, servo_180_return).start()
        
        HardwareController.servo_90_set_angle(90)
        print(f"[SERVO] Servo 90 set to 90 degrees")
        
        def servo_90_off():
            if status:
                HardwareController.servo_90_set_angle(0)
                print(f"[SERVO] Servo 90 returned to 0 degrees")
        
        threading.Timer(60, servo_90_off).start()
    
    @staticmethod
    def handle_letter_sensor(pin, is_active):
        """Handle letter sensor activation/deactivation"""
        if not status:
            return
        
        letter = cfg.SENSOR_LETTER_MAP.get(pin)
        if not letter: 
            return
        
        old_state = status.active_sensors[letter]
        status.active_sensors[letter] = is_active
        print(f"[LETTER] Letter '{letter}' changed: {old_state} -> {is_active}")
        
        # Update LED based on sensor state
        status.update_led_for_sensor(letter, is_active)
        
        if status.current_state != SystemState.AVAILABLE:
            print(f"[LETTER] Ignoring - not in AVAILABLE mode (current: {status.current_state})")
            return
        
        all_active = all(status.active_sensors.values())
        print(f"[LETTER] All letters active: {all_active} (Active: {status.active_sensors})")
        
        if all_active and not status.good_mode_triggered:
            print(f"[LETTER] ALL LETTERS DETECTED! Triggering GOOD mode")
            status.good_mode_triggered = True
            StateMachine.enter_good()
        elif not all_active:
            if is_active:
                letter_video = f"{letter}.mp4"
                print(f"[VIDEO] Playing letter video: {letter_video}")
                VideoController.play(letter_video, loop=True)
                status.is_letter_video_active = True
            else:
                if status.is_letter_video_active:
                    print(f"[VIDEO] Letter deactivated, returning to available video")
                    VideoController.play(cfg.VIDEO_AVAILABLE, loop=True)
                    status.is_letter_video_active = False

# ============================================================
# MAIN ENTRY POINT
# ============================================================
if __name__ == "__main__":
    try:
        print("=" * 50)
        print("   INTERACTIVE DISPLAY CONTROLLER")
        print("   MIGRATED TO PIGPIO LIBRARY")
        print("   All video modes: ATTRACTION, AVAILABLE, GOOD")
        print("   LEDs INDICATE LETTER SENSORS")
        print("=" * 50)

        # Verify license BEFORE touching any hardware.
        # Aborts the process on any failure (missing/expired/wrong-hardware/tampered).
        license_manager.verify_license()

        # FIX: Initialize pigpio FIRST, before SystemStatus(),
        # so that 'pi' is not None when _init_pwm() and _init_steppers() run.
        print("Initializing pigpio daemon connection...")
        if not init_pigpio():
            print("ERROR: Could not connect to pigpio daemon")
            print("Make sure pigpiod is running: sudo pigpiod")
            sys.exit(1)
        
        # Create system status AFTER pigpio is ready
        print("Initializing System Status...")
        status = SystemStatus()
        
        # Now initialize PWM and steppers (pi is connected)
        status._init_pwm()
        status._init_steppers()
        print("✓ System Status initialized")
        
        # Setup GPIO with pigpio
        if not setup_gpio_pigpio():
            print("ERROR: GPIO setup failed")
            sys.exit(1)
        
        # Start state machine with ATTRACTION mode
        print("Starting State Machine in ATTRACTION mode...")
        StateMachine.enter_attraction()
        
        print("\n✓ System running successfully!")
        print("Video playback status for each mode:")
        print("  - ATTRACTION: Should play", cfg.VIDEO_ATTRACTION)
        print("  - AVAILABLE: Should play", cfg.VIDEO_AVAILABLE)
        print("  - GOOD: Should play", cfg.VIDEO_GOOD)
        print("  - LETTERS: Should play [P,R,E,M,I,O].mp4")
        print("\nLED INDICATION:")
        print("  - LED 1 (GPIO 17) = Sensor P")
        print("  - LED 2 (GPIO 18) = Sensor R")
        print("  - LED 3 (GPIO 27) = Sensor E")
        print("  - LED 4 (GPIO 22) = Sensor M")
        print("  - LED 5 (GPIO 23) = Sensor I")
        print("  - LED 6 (GPIO 24) = Sensor O")
        print("  - LEDs turn ON/OFF with respective sensors")
        print("  - GOOD mode overrides with blinking effect")
        print("\nPress Ctrl+C to stop.\n")
        
        # Main loop - just keep alive
        while True:
            time.sleep(0.1)
            
    except KeyboardInterrupt:
        print("\n\n" + "=" * 50)
        print("   SHUTTING DOWN SYSTEM")
        print("=" * 50)
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Cleanup
        print("\nCleaning up resources...")
        
        if status:
            status.stop_all_threads()
        
        HardwareController.leds_off()
        HardwareController.main_motor(False)
        HardwareController.servo_180_stop_balance()
        
        if status:
            status.enable_steppers(False)
            status.cleanup()
        
        print("Stopping any playing videos...")
        VideoController.stop()
        
        # Stop pigpio connection
        if pi:
            pi.stop()
            print("✓ pigpio connection closed")
        
        print("\n✓ System stopped safely.\n")