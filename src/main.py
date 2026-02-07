import sys
import json
import subprocess
import threading
import time
import random
import re
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, List
import ctypes
import os

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QFileDialog, QTextEdit, QTabWidget,
    QTableWidget, QTableWidgetItem, QSpinBox, QTimeEdit, QComboBox,
    QMessageBox, QDialog, QFormLayout, QCheckBox, QProgressDialog
)
from PyQt6.QtCore import Qt, QTimer, QTime, pyqtSignal, QThread
from PyQt6.QtGui import QColor, QFont

from wakeup_monitor import MonitorControl


class Logger:
    """Thread-safe logging to logs/ folder with timestamped files"""
    def __init__(self):
        self.logs_dir = Path("logs")
        self.logs_dir.mkdir(exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = self.logs_dir / f"log_{timestamp}.txt"
        self.log_file.touch(exist_ok=True)

    def log(self, message: str, level: str = "INFO"):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] [{level}] {message}"
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(log_entry + '\n')
        print(log_entry)

    def read_logs(self, lines: int = 100) -> str:
        try:
            with open(self.log_file, 'r', encoding='utf-8') as f:
                all_lines = f.readlines()
                return ''.join(all_lines[-lines:])
        except FileNotFoundError:
            return "No logs yet."


class ScheduleManager:
    """Manages schedule loading and manipulation"""
    def __init__(self, schedule_file: str = "schedule.json"):
        self.schedule_file = Path(schedule_file)
        self.schedule: List[Dict] = []
        self.load_schedule()

    def load_schedule(self):
        if not self.schedule_file.exists():
            self.schedule = []
            return

        try:
            with open(self.schedule_file, 'r', encoding='utf-8') as f:
                self.schedule = json.load(f)
        except Exception as e:
            print(f"Error loading schedule: {e}")
            self.schedule = []

    def save_schedule(self):
        try:
            with open(self.schedule_file, 'w', encoding='utf-8') as f:
                json.dump(self.schedule, f, indent=2)
        except Exception as e:
            print(f"Error saving schedule: {e}")

    def add_entry(self, start_time: str, duration: int, url: str = ""):
        entry = {
            "start_time": start_time,
            "duration_minutes": duration,
            "youtube_url": url,
            "enabled": True
        }
        self.schedule.append(entry)
        self.save_schedule()

    def remove_entry(self, index: int):
        if 0 <= index < len(self.schedule):
            self.schedule.pop(index)
            self.save_schedule()

    def set_entry_enabled(self, index: int, enabled: bool):
        if 0 <= index < len(self.schedule):
            self.schedule[index]["enabled"] = enabled
            self.save_schedule()

    def get_schedule(self) -> List[Dict]:
        return self.schedule


class URLProvider:
    """Manages random URL selection"""
    def __init__(self, url_file: str = "youtube_url.txt"):
        self.url_file = Path(url_file)
        self.ensure_file()

    def ensure_file(self):
        if not self.url_file.exists():
            self.url_file.touch()

    def get_random_url(self) -> Optional[str]:
        try:
            with open(self.url_file, 'r', encoding='utf-8') as f:
                urls = [line.strip() for line in f if line.strip()]
                return random.choice(urls) if urls else None
        except Exception:
            return None

    def add_url(self, url: str):
        with open(self.url_file, 'a', encoding='utf-8') as f:
            f.write(url + '\n')


class YouTubePlaylistURLFetcher(QThread):
    """Fetches all video URLs from a YouTube playlist"""
    progress = pyqtSignal(str)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, playlist_url: str):
        super().__init__()
        self.playlist_url = playlist_url
        self.urls = []

    def run(self):
            """Main playback loop"""
            self.logger.log("Playback scheduler started")
            self.log_signal.emit("Scheduler", "Playback scheduler started")

            while self.running:
                try:
                    current_time = datetime.now().strftime("%H:%M:%S")
                    self.logger.log(f"[DEBUG] Loop iteration - Time: {current_time}, Playback active: {self.playback_active}")
                    
                    self.check_and_execute_schedule()
                    self.monitor_playback()
                    time.sleep(5)
                except Exception as e:
                    self.logger.log(f"Error in playback loop: {e}", "ERROR")
                    self.log_signal.emit("ERROR", str(e))

    def extract_playlist_videos(self, playlist_url: str) -> List[str]:
        """Extract video IDs from playlist"""
        try:
            urls = self.scrape_playlist_html(playlist_url)
            return urls
        except Exception as e:
            raise Exception(f"Failed to extract playlist: {str(e)}")

    def scrape_playlist_html(self, playlist_url: str) -> List[str]:
        """Scrape playlist page for video URLs"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            req = urllib.request.Request(playlist_url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as response:
                html = response.read().decode('utf-8')
            
            # Extract video IDs from HTML using regex
            video_ids = set()
            pattern = r'watch\?v=([a-zA-Z0-9_-]{11})'
            matches = re.findall(pattern, html)
            
            for match in matches:
                if match not in video_ids:
                    video_ids.add(match)
            
            # Convert to full URLs
            urls = [f"https://www.youtube.com/watch?v={vid}" for vid in video_ids]
            return urls
            
        except Exception as e:
            raise Exception(f"Failed to scrape playlist: {str(e)}")


class PlaybackWorker(QThread):
    """Runs in separate thread to manage scheduled playback"""
    status_signal = pyqtSignal(str)
    log_signal = pyqtSignal(str, str)

    def __init__(self, logger: Logger, schedule_mgr: ScheduleManager,
                 url_provider: URLProvider, mpv_path: str):
        super().__init__()
        self.logger = logger
        self.schedule_mgr = schedule_mgr
        self.url_provider = url_provider
        self.mpv_path = mpv_path
        self.monitor_control = MonitorControl()
        self.running = True
        self.current_process: Optional[subprocess.Popen] = None
        self.playback_active = False
        self.playback_start_time: Optional[datetime] = None
        self.playback_duration_minutes = 0
        self.playback_scheduled_entry: Optional[Dict] = None
        self.scheduled_entries_executed = set()

    def run(self):
        """Main playback loop"""
        self.logger.log("Playback scheduler started")
        self.log_signal.emit("Scheduler", "Playback scheduler started")

        while self.running:
            try:
                self.check_and_execute_schedule()
                self.monitor_playback()
                time.sleep(5)
            except Exception as e:
                self.logger.log(f"Error in playback loop: {e}", "ERROR")
                self.log_signal.emit("ERROR", str(e))

    def check_and_execute_schedule(self):
            """Check if any schedule entry should start now"""
            if self.playback_active:
                self.logger.log("[DEBUG] check_and_execute_schedule: Playback already active, skipping")
                return

            now = datetime.now()
            current_time = now.strftime("%H:%M")
            entry_key = current_time

            if entry_key in self.scheduled_entries_executed:
                self.logger.log(f"[DEBUG] check_and_execute_schedule: Entry {entry_key} already executed")
                return

            schedule = self.schedule_mgr.get_schedule()
            self.logger.log(f"[DEBUG] check_and_execute_schedule: Checking {len(schedule)} schedule entries for time {current_time}")
            
            for entry in schedule:
                scheduled_time = entry.get("start_time", "")
                enabled = entry.get("enabled", True)
                
                self.logger.log(f"[DEBUG] Checking entry: {scheduled_time}, enabled: {enabled}, matches: {scheduled_time == current_time}")
                
                if scheduled_time == current_time and enabled:
                    self.scheduled_entries_executed.add(entry_key)
                    self.logger.log(f"[DEBUG] Executing scheduled entry for {current_time}")
                    self.execute_playback(entry, now)
                    break

            now_hour = now.strftime("%H")
            self.scheduled_entries_executed = {
                k for k in self.scheduled_entries_executed
                if k >= (now - timedelta(hours=2)).strftime("%H:%M")
            }

    def monitor_playback(self):
            """Monitor active playback and handle video switching"""
            if not self.playback_active:
                self.logger.log("[DEBUG] monitor_playback: No active playback")
                return

            self.logger.log(f"[DEBUG] monitor_playback: Monitoring active playback, process alive: {self.current_process and self.current_process.poll() is None}")

            if self.current_process and self.current_process.poll() is not None:
                self.playback_active = False
                self.logger.log("[DEBUG] Current video ended, checking for next...")
                self.play_next_video()
                return

            if self.playback_start_time and self.playback_duration_minutes:
                elapsed_minutes = (datetime.now() - self.playback_start_time).total_seconds() / 60
                self.logger.log(f"[DEBUG] Elapsed time: {elapsed_minutes:.2f}/{self.playback_duration_minutes} minutes")
                if elapsed_minutes >= self.playback_duration_minutes:
                    self.logger.log(f"Scheduled duration ({self.playback_duration_minutes}min) reached")
                    self.stop_mpv()
                    self.playback_active = False
                    # Release display required flag
                    try:
                        self.logger.log("[DEBUG] Releasing display required flag after duration reached")
                        self.monitor_control.release_display_required()
                    except Exception as e:
                        self.logger.log(f"Could not release display flag: {e}", "WARNING")

    def play_next_video(self):
            """Play the next random video if still within session duration"""
            self.logger.log("[DEBUG] play_next_video called")
            if not self.playback_scheduled_entry or not self.playback_start_time:
                self.logger.log("[DEBUG] No scheduled entry or start time, exiting")
                return

            duration = self.playback_duration_minutes
            elapsed_minutes = (datetime.now() - self.playback_start_time).total_seconds() / 60

            self.logger.log(f"[DEBUG] play_next_video: {elapsed_minutes:.2f}/{duration} minutes elapsed")

            if elapsed_minutes < duration:
                url = self.url_provider.get_random_url()
                if url:
                    msg = f"Playing next video: {url}"
                    self.logger.log(msg, "INFO")
                    self.log_signal.emit("PLAYBACK", msg)
                    self.start_mpv(url)
                else:
                    msg = "No more URLs available"
                    self.logger.log(msg, "WARNING")
            else:
                msg = "Scheduled duration finished"
                self.logger.log(msg, "INFO")
                self.playback_active = False
                # Release display flag when session ends
                try:
                    self.logger.log("[DEBUG] play_next_video: Releasing display flag - session ended")
                    self.monitor_control.release_display_required()
                except Exception as e:
                    self.logger.log(f"Could not release display flag: {e}", "WARNING")

    def execute_playback(self, entry: Dict, scheduled_time: datetime):
        """Execute a single playback session"""
        # Use entry-specific URL if available, otherwise use random URL
        url = entry.get("youtube_url", "").strip()
        if not url:
            url = self.url_provider.get_random_url()
        
        if not url:
            msg = "No URL available (no entry URL and no random URLs in youtube_url.txt)"
            self.logger.log(msg, "ERROR")
            self.log_signal.emit("ERROR", msg)
            return

        duration = entry.get("duration_minutes", 60)

        msg = f"Starting playback session: {duration}min duration, URL: {url}"
        self.logger.log(msg, "INFO")
        self.log_signal.emit("PLAYBACK", msg)

        self.playback_active = True
        self.playback_start_time = scheduled_time
        self.playback_duration_minutes = duration
        self.playback_scheduled_entry = entry

        self.wake_system()
        self.start_mpv(url)

    def start_mpv(self, url: str):
        """Launch MPV player in fullscreen"""
        if not Path(self.mpv_path).exists():
            msg = f"MPV not found at {self.mpv_path}"
            self.logger.log(msg, "ERROR")
            self.log_signal.emit("ERROR", msg)
            return

        try:
            self.current_process = subprocess.Popen(
                [self.mpv_path, "--fullscreen", url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
            )
            self.logger.log(f"MPV started in fullscreen (PID: {self.current_process.pid}) - {url}")
        except Exception as e:
            self.logger.log(f"Failed to start MPV: {e}", "ERROR")
            self.log_signal.emit("ERROR", f"Failed to start MPV: {e}")
            self.playback_active = False

    def stop_mpv(self):
            """Terminate MPV player gracefully"""
            self.logger.log(f"[DEBUG] stop_mpv called, process exists: {self.current_process is not None}")
            if self.current_process and self.current_process.poll() is None:
                try:
                    self.logger.log("[DEBUG] Terminating MPV process")
                    self.current_process.terminate()
                    self.current_process.wait(timeout=5)
                    self.logger.log("MPV stopped gracefully")
                    self.log_signal.emit("PLAYBACK", "MPV stopped")
                except subprocess.TimeoutExpired:
                    self.current_process.kill()
                    self.logger.log("MPV killed (timeout)")
                except Exception as e:
                    self.logger.log(f"Error stopping MPV: {e}", "ERROR")
            
            # Release display required flag to allow auto-sleep
            try:
                self.logger.log("[DEBUG] stop_mpv: Releasing display required flag")
                self.monitor_control.release_display_required()
            except Exception as e:
                self.logger.log(f"Could not release display flag: {e}", "WARNING")

    def wake_system(self):
            """Wake system from sleep using MonitorControl"""
            try:
                self.logger.log("[DEBUG] wake_system: Calling ensure_monitor_on()")
                self.monitor_control.ensure_monitor_on()
                self.logger.log("System wake-up signal sent")
            except Exception as e:
                self.logger.log(f"Could not wake system: {e}", "WARNING")

    def stop(self):
        """Stop the scheduler"""
        self.running = False
        self.stop_mpv()
        self.logger.log("Playback scheduler stopped")


class SettingsDialog(QDialog):
    """Settings dialog for MPV path"""
    def __init__(self, parent, current_mpv_path: str):
        super().__init__(parent)
        self.mpv_path = current_mpv_path
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("Settings")
        self.setGeometry(200, 200, 500, 150)

        layout = QFormLayout()

        label = QLabel("MPV Executable Path:")
        self.path_input = QLineEdit(self.mpv_path)
        browse_btn = QPushButton("Browse")
        browse_btn.clicked.connect(self.browse_mpv)

        path_layout = QHBoxLayout()
        path_layout.addWidget(self.path_input)
        path_layout.addWidget(browse_btn)

        layout.addRow(label, path_layout)

        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)

        btn_layout = QHBoxLayout()
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addRow(btn_layout)

        self.setLayout(layout)

    def browse_mpv(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select MPV Executable", "",
            "Executable Files (*.exe);;All Files (*)"
        )
        if path:
            self.path_input.setText(path)

    def get_mpv_path(self) -> str:
        return self.path_input.text()


class MainWindow(QMainWindow):
    """Main application window"""
    def __init__(self):
        super().__init__()
        self.logger = Logger()
        self.schedule_mgr = ScheduleManager()
        self.url_provider = URLProvider()
        self.config_file = Path("config.json")
        self.mpv_path = self.load_config()
        self.playback_worker: Optional[PlaybackWorker] = None
        self.fetcher: Optional[YouTubePlaylistURLFetcher] = None

        self.init_ui()
        self.start_scheduler()

    def init_ui(self):
        self.setWindowTitle("YouTube MPV Scheduler v1.0.0")
        self.setGeometry(100, 100, 1000, 700)

        main_widget = QWidget()
        main_layout = QVBoxLayout()

        tabs = QTabWidget()

        schedule_tab = self.create_schedule_tab()
        tabs.addTab(schedule_tab, "Schedule")

        urls_tab = self.create_urls_tab()
        tabs.addTab(urls_tab, "Random URLs")

        logs_tab = self.create_logs_tab()
        tabs.addTab(logs_tab, "Logs")

        main_layout.addWidget(tabs)

        ctrl_layout = QHBoxLayout()
        
        settings_btn = QPushButton("Settings")
        settings_btn.clicked.connect(self.open_settings)
        ctrl_layout.addWidget(settings_btn)
        
        ctrl_layout.addStretch()
        
        refresh_logs_btn = QPushButton("Refresh Logs")
        refresh_logs_btn.clicked.connect(self.refresh_logs)
        ctrl_layout.addWidget(refresh_logs_btn)

        main_layout.addLayout(ctrl_layout)

        main_widget.setLayout(main_layout)
        self.setCentralWidget(main_widget)

    def create_schedule_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout()

        self.schedule_table = QTableWidget()
        self.schedule_table.setColumnCount(6)
        self.schedule_table.setHorizontalHeaderLabels(
            ["Start Time", "Duration (min)", "YouTube URL", "Enable", "Disable", "Remove"]
        )
        self.schedule_table.setColumnWidth(0, 100)
        self.schedule_table.setColumnWidth(1, 120)
        self.schedule_table.setColumnWidth(2, 410)
        layout.addWidget(QLabel("Schedule:"))
        layout.addWidget(self.schedule_table)

        form_layout = QHBoxLayout()

        form_layout.addWidget(QLabel("Start Time (HH:MM):"))
        self.time_input = QLineEdit()
        self.time_input.setPlaceholderText("14:30")
        self.time_input.setFixedWidth(80)
        form_layout.addWidget(self.time_input)

        form_layout.addWidget(QLabel("Duration (min):"))
        self.duration_input = QSpinBox()
        self.duration_input.setMinimum(1)
        self.duration_input.setMaximum(1440)
        self.duration_input.setValue(60)
        form_layout.addWidget(self.duration_input)

        form_layout.addWidget(QLabel("YouTube URL (optional):"))
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://www.youtube.com/watch?v=...")
        self.url_input.setMinimumWidth(300)
        form_layout.addWidget(self.url_input)

        add_btn = QPushButton("Add Entry")
        add_btn.clicked.connect(self.add_schedule_entry)
        form_layout.addWidget(add_btn)

        layout.addLayout(form_layout)
        widget.setLayout(layout)
        self.refresh_schedule_table()
        return widget

    def create_urls_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout()

        layout.addWidget(QLabel("Download URLs from YouTube Playlist:"))
        
        playlist_layout = QHBoxLayout()
        self.playlist_input = QLineEdit()
        self.playlist_input.setPlaceholderText("https://www.youtube.com/playlist?list=PLxxxxxx")
        playlist_layout.addWidget(self.playlist_input)
        
        fetch_btn = QPushButton("Fetch & Append URLs")
        fetch_btn.clicked.connect(self.fetch_playlist_urls)
        playlist_layout.addWidget(fetch_btn)
        
        layout.addLayout(playlist_layout)
        layout.addWidget(QLabel(""))

        layout.addWidget(QLabel("Random YouTube URLs (one per line):"))

        self.urls_text = QTextEdit()
        try:
            with open("youtube_url.txt", 'r', encoding='utf-8') as f:
                self.urls_text.setPlainText(f.read())
        except FileNotFoundError:
            pass

        layout.addWidget(self.urls_text)

        save_urls_btn = QPushButton("Save URLs")
        save_urls_btn.clicked.connect(self.save_urls)
        layout.addWidget(save_urls_btn)

        widget.setLayout(layout)
        return widget

    def create_logs_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout()

        self.logs_text = QTextEdit()
        self.logs_text.setReadOnly(True)
        font = QFont("Courier")
        font.setPointSize(9)
        self.logs_text.setFont(font)
        layout.addWidget(self.logs_text)

        widget.setLayout(layout)
        self.refresh_logs()
        return widget

    def add_schedule_entry(self):
        time_str = self.time_input.text().strip()
        duration = self.duration_input.value()
        url = self.url_input.text().strip()

        if not time_str:
            QMessageBox.warning(self, "Input Error", "Please enter start time")
            return

        try:
            datetime.strptime(time_str, "%H:%M")
        except ValueError:
            QMessageBox.warning(self, "Input Error", "Invalid time format. Use HH:MM")
            return

        self.schedule_mgr.add_entry(time_str, duration, url)
        self.refresh_schedule_table()
        self.time_input.clear()
        self.url_input.clear()
        url_info = f" - {url}" if url else " - random URL"
        self.logger.log(f"Added schedule: {time_str} ({duration}min){url_info}")

    def refresh_schedule_table(self):
        self.schedule_table.setRowCount(0)
        for idx, entry in enumerate(self.schedule_mgr.get_schedule()):
            self.schedule_table.insertRow(idx)

            time_item = QTableWidgetItem(entry.get("start_time", ""))
            self.schedule_table.setItem(idx, 0, time_item)

            dur_item = QTableWidgetItem(str(entry.get("duration_minutes", 0)))
            self.schedule_table.setItem(idx, 1, dur_item)

            url = entry.get("youtube_url", "")
            url_display = url if url else "(Random URL)"
            url_item = QTableWidgetItem(url_display)
            self.schedule_table.setItem(idx, 2, url_item)

            # Enable button
            enable_btn = QPushButton("Enable")
            enable_btn.clicked.connect(lambda checked, i=idx: self.enable_schedule_entry(i))
            self.schedule_table.setCellWidget(idx, 3, enable_btn)

            # Disable button
            disable_btn = QPushButton("Disable")
            disable_btn.clicked.connect(lambda checked, i=idx: self.disable_schedule_entry(i))
            self.schedule_table.setCellWidget(idx, 4, disable_btn)

            # Remove button
            remove_btn = QPushButton("Remove")
            remove_btn.clicked.connect(lambda checked, i=idx: self.remove_schedule_entry(i))
            self.schedule_table.setCellWidget(idx, 5, remove_btn)

            # Update button states based on enabled status
            enabled = entry.get("enabled", True)
            enable_btn.setEnabled(not enabled)
            disable_btn.setEnabled(enabled)

    def enable_schedule_entry(self, index: int):
        self.schedule_mgr.set_entry_enabled(index, True)
        self.refresh_schedule_table()
        self.logger.log(f"Enabled schedule entry at index {index}")

    def disable_schedule_entry(self, index: int):
        self.schedule_mgr.set_entry_enabled(index, False)
        self.refresh_schedule_table()
        self.logger.log(f"Disabled schedule entry at index {index}")

    def remove_schedule_entry(self, index: int):
        self.schedule_mgr.remove_entry(index)
        self.refresh_schedule_table()
        self.logger.log(f"Removed schedule entry at index {index}")

    def save_urls(self):
        urls = self.urls_text.toPlainText()
        try:
            with open("youtube_url.txt", 'w', encoding='utf-8') as f:
                f.write(urls)
            QMessageBox.information(self, "Success", "URLs saved!")
            self.logger.log("Updated youtube_url.txt")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save: {e}")

    def fetch_playlist_urls(self):
        """Fetch URLs from YouTube playlist and append to file"""
        playlist_url = self.playlist_input.text().strip()
        
        if not playlist_url:
            QMessageBox.warning(self, "Input Error", "Please enter a playlist URL")
            return
        
        if "youtube.com/playlist" not in playlist_url:
            QMessageBox.warning(self, "Input Error", "Please enter a valid YouTube playlist URL")
            return
        
        progress = QProgressDialog("Fetching playlist URLs...", "Cancel", 0, 0, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.show()
        
        self.fetcher = YouTubePlaylistURLFetcher(playlist_url)
        self.fetcher.finished.connect(lambda urls: self.on_playlist_fetched(urls, progress))
        self.fetcher.error.connect(lambda msg: self.on_playlist_error(msg, progress))
        self.fetcher.progress.connect(lambda msg: self.update_progress(msg, progress))
        self.fetcher.start()

    def on_playlist_fetched(self, urls: List[str], progress):
        """Handle fetched playlist URLs"""
        progress.close()
        
        if not urls:
            QMessageBox.warning(self, "No Videos", "No videos found in playlist")
            return
        
        current_text = self.urls_text.toPlainText().strip()
        existing_urls = set(line.strip() for line in current_text.split('\n') if line.strip())
        new_urls = [url for url in urls if url not in existing_urls]
        
        if new_urls:
            if current_text:
                combined = current_text + '\n' + '\n'.join(new_urls)
            else:
                combined = '\n'.join(new_urls)
            
            self.urls_text.setPlainText(combined)
            QMessageBox.information(
                self, "Success",
                f"Added {len(new_urls)} new URLs from playlist!\n"
                f"({len(existing_urls)} duplicates skipped)"
            )
            self.logger.log(f"Added {len(new_urls)} URLs from playlist")
        else:
            QMessageBox.information(self, "Info", "All playlist URLs already exist")

    def on_playlist_error(self, error_msg: str, progress):
        """Handle playlist fetch error"""
        progress.close()
        QMessageBox.critical(self, "Error", error_msg)
        self.logger.log(f"Playlist fetch error: {error_msg}", "ERROR")

    def update_progress(self, msg: str, progress):
        """Update progress dialog text"""
        progress.setLabelText(msg)

    def refresh_logs(self):
        logs = self.logger.read_logs(200)
        self.logs_text.setPlainText(logs)
        self.logs_text.verticalScrollBar().setValue(
            self.logs_text.verticalScrollBar().maximum()
        )

    def open_settings(self):
        dialog = SettingsDialog(self, self.mpv_path)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.mpv_path = dialog.get_mpv_path()
            self.save_config()
            self.logger.log(f"MPV path updated: {self.mpv_path}")

    def load_config(self) -> str:
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
                return config.get("mpv_path", "C:\\Program Files\\mpv\\mpv.exe")
        except FileNotFoundError:
            return "C:\\Program Files\\mpv\\mpv.exe"

    def save_config(self):
        config = {"mpv_path": self.mpv_path}
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2)

    def start_scheduler(self):
        if self.playback_worker is None:
            self.playback_worker = PlaybackWorker(
                self.logger, self.schedule_mgr, self.url_provider, self.mpv_path
            )
            self.playback_worker.log_signal.connect(self.on_worker_log)
            self.playback_worker.start()

    def on_worker_log(self, level: str, message: str):
        self.refresh_logs()

    def closeEvent(self, event):
        if self.playback_worker:
            self.playback_worker.stop()
            self.playback_worker.wait()
        event.accept()


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()