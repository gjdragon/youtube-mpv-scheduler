"""Monitor control module for waking system from sleep."""

import time
import logging
from ctypes import windll, c_int, Structure, sizeof, byref


class LASTINPUTINFO(Structure):
    """Windows API structure for last input info."""
    _fields_ = [
        ('cbSize', c_int),
        ('dwTime', c_int),
    ]


class MonitorControl:
    """Handles monitor wake-up and power state management."""

    # Windows Monitor Power Constants
    HWND_BROADCAST = 0xFFFF
    WM_SYSCOMMAND = 0x0112
    SC_MONITORPOWER = 0xF170
    MONITOR_ON = -1
    MONITOR_OFF = 2

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def get_idle_time_seconds(self):
        """Return system idle time in seconds."""
        last_input = LASTINPUTINFO()
        last_input.cbSize = sizeof(LASTINPUTINFO)

        if not windll.user32.GetLastInputInfo(byref(last_input)):
            raise RuntimeError("GetLastInputInfo failed")

        millis = windll.kernel32.GetTickCount() - last_input.dwTime
        return millis / 1000.0

    def force_display_on(self):
        """Force display on using multiple Windows API calls."""
        try:
            # Method 1: Send monitor power on command
            windll.user32.PostMessageW(
                self.HWND_BROADCAST,
                self.WM_SYSCOMMAND,
                self.SC_MONITORPOWER,
                self.MONITOR_ON
            )

            # Method 2: Prevent system sleep
            ES_CONTINUOUS = 0x80000000
            ES_SYSTEM_REQUIRED = 0x00000001
            ES_DISPLAY_REQUIRED = 0x00000002

            windll.kernel32.SetThreadExecutionState(
                ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
            )

            # Method 3: Simulate key input (Shift, Ctrl, Alt)
            for key in (0x10, 0x11, 0x12):
                windll.user32.keybd_event(key, 0, 0, 0)
                time.sleep(0.05)
                windll.user32.keybd_event(key, 0, 2, 0)

            self.logger.info("Display wake command sent successfully")
            return True

        except Exception as e:
            self.logger.exception("Error in force_display_on")
            return False

    def ensure_monitor_on(self, max_attempts=3):
        """Ensure monitor is powered on with multiple attempts."""
        for attempt in range(1, max_attempts + 1):
            self.logger.info(f"Attempt {attempt} to wake monitor")
            if self.force_display_on():
                return True
            time.sleep(1)
        return False


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )

    mc = MonitorControl()

    try:
        idle = mc.get_idle_time_seconds()
        logging.info(f"System idle time: {idle:.1f} seconds")
    except Exception as e:
        logging.error(f"Idle time check failed: {e}")

    success = mc.ensure_monitor_on()

    if success:
        logging.info("Monitor wake test completed successfully")
    else:
        logging.error("Monitor wake test failed")