# YouTube MPV Scheduler

A Windows GUI application that plays random YouTube videos at scheduled times using the MPV player.

## Features

- **Scheduled Playback**: Set specific times for videos to start
- **Fullscreen Mode**: Videos play in fullscreen automatically
- **Random Video Queue**: Continuously plays random videos from `youtube_url.txt` for the scheduled duration
- **Single Instance**: Only one video plays at a time
- **Auto Video Switching**: Seamlessly picks the next random video when current one ends
- **Comprehensive Logging**: All events logged to `timestamps_log.txt` with timestamps
- **Settings Persistence**: MPV path and schedules saved automatically

## Requirements

- Windows OS
- Python 3.8+
- PyQt6
- MPV player

## Installation

1. **Install Python dependencies:**
   ```bash
   pip install PyQt6
   ```

2. **Download and install MPV:**
   - Visit https://mpv.io/installation/

3. **Run the application:**
   ```bash
   python src/main.py
   ```

## Setup

### 1. Configure MPV Path
- Click **Settings** button
- Browse to your MPV executable (usually `C:\Program Files\mpv\mpv.exe`)
- Click **Save**

### 2. Add YouTube URLs
- Click the **Random URLs** tab
- Paste YouTube URLs (one per line)
- Click **Save URLs**

Example:
```
https://www.youtube.com/watch?v=dQw4w9WgXcQ
```

### 3. Create Schedule
- Click the **Schedule** tab
- Enter start time (HH:MM format, e.g., `14:30`)
- Enter duration in minutes
- Click **Add Entry**

## Files

- `youtube_mpv_scheduler.py` - Main application
- `schedule.json` - Scheduled playback entries
- `youtube_url.txt` - Random YouTube URLs (one per line)
- `config.json` - MPV path configuration
- `timestamps_log.txt` - Activity log with timestamps

## How It Works

1. Application monitors scheduled times
2. At scheduled time, picks a random URL from `youtube_url.txt`
3. Launches MPV in fullscreen with the URL
4. When video ends, automatically plays next random video
5. Continues until scheduled duration expires
6. All actions logged to `timestamps_log.txt`

## Keyboard Shortcuts (MPV)

- **ESC** - Exit fullscreen / Stop playback
- **Space** - Pause/Resume
- **→** - Skip forward 5 seconds
- **←** - Skip backward 5 seconds
- **M** - Toggle mute

## Logs

View application logs in the **Logs** tab or open `timestamps_log.txt` directly. Logs include:
- Scheduled playback start/stop times
- Video URLs played
- Video switches
- Errors and warnings

## License

Open source - feel free to modify and distribute.