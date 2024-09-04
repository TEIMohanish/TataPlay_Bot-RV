import os
import subprocess
import requests
import asyncio
import time
import logging
import glob
from pyrogram import Client, filters
from pyrogram.types import Message
import yt_dlp

# Setup logging
logging.basicConfig(level=logging.INFO)

# Configuration
PLAYERX_API_URL = "https://www.playerx.stream/api.php"
PLAYERX_API_KEY = "46topBnuEaqZ5FRf"
MAX_RETRIES = 3
SUDO_USERS = [2023056811, -1002248603989, 1137065263]  # Add sudo users here
AUTHORIZED_GROUP = -1002248603989  # Group ID for authorized members

# In-memory storage for user settings
user_settings = {}

# Initialize the Pyrogram client
api_id = 7331082
api_hash = "5d4a78eeed44e18e97bc4ce58e397e15"
bot_token = "6009987351:AAFY8_hxgcME2yKzkFCrbITSjapw8vwweog"
app = Client("mytbot", api_id=api_id, api_hash=api_hash, bot_token=bot_token)

# Progress bar helper function
def create_progress_bar(current, total, length=20):
    progress = int((current / total) * length)
    bar = f"[{'●' * progress}{'○' * (length - progress)}]"
    return bar

# Function to update progress on the same message
async def update_progress_message(message: Message, phase, filename, current, total, speed, eta, last_update_time, last_message_content):
    if time.time() - last_update_time < 5:
        return last_update_time, last_message_content

    r = 'Sec' if phase in ['Recording', 'Downloading'] else 'MB'
    progress_bar = create_progress_bar(current, total)
    current_rounded = round(current, 2)
    total_rounded = round(total, 2)
    speed_rounded = round(speed, 2)
    new_message_content = (
        f"[+] {phase}\n"
        f" {filename}\n"
        f"{progress_bar} \n"
        f"Process: {round((current / total) * 100, 2)}%\n"
        f"{current_rounded}{r} of {total_rounded}{r}\n"
        f"Speed: {speed_rounded} MB/s\n"
        f"ETA: {eta}s"
    )
    
    if new_message_content != last_message_content:
        try:
            await message.edit_text(new_message_content)
            last_message_content = new_message_content
        except Exception as e:
            logging.warning(f"Failed to update message: {e}")

    return time.time(), last_message_content

# Function to handle recording and uploading with multi-audio
async def handle_recording(message: Message, m3u8_url, duration, filename, user, upload_destination, audio_languages):
    output_file = f"{filename}.mkv"
    total_duration = int(duration.split(':')[0]) * 3600 + int(duration.split(':')[1]) * 60 + int(duration.split(':')[2])
    
    # Start the initial message
    progress_message = await message.reply_text(f"Starting recording of {filename}...")

    # Build ffmpeg audio map commands for each language
    audio_map = []
    for idx, language in enumerate(audio_languages, start=1):
        audio_map.extend(["-map", f"0:a:{idx}", "-metadata:s:a:{idx}", f"title=[ToonEncoaders] - {language}"])

    # Record the stream using ffmpeg
    try:
        start_time = time.time()
        ffmpeg_command = [
            "ffmpeg", "-y", "-i", m3u8_url,
            "-t", duration, "-c", "copy"
            , output_file]

        ffmpeg_process = subprocess.Popen(
            ffmpeg_command,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True
        )

        current_time = 0
        last_update_time = 0
        last_message_content = ""
        while ffmpeg_process.poll() is None:
            line = ffmpeg_process.stdout.readline()
            if "time=" in line:
                time_str = line.split("time=")[-1].split(" ")[0]
                try:
                    h, m, s = map(float, time_str.split(':'))
                    current_time = int(h) * 3600 + int(m) * 60 + int(s)
                except ValueError:
                    continue  # Ignore lines that don't match the expected format

                elapsed_time = time.time() - start_time
                speed = current_time / elapsed_time if elapsed_time > 0 else 0
                eta = int((total_duration - current_time) / speed) if speed > 0 else total_duration

                last_update_time, last_message_content = await update_progress_message(
                    progress_message, "Recording", filename, current_time, total_duration, speed, eta, last_update_time, last_message_content
                )

        if ffmpeg_process.returncode != 0:
            await message.reply_text("Recording failed.")
            return

    except Exception as e:
        await message.reply_text(f"Recording failed. Error: {str(e)}")
        return

    # Wait for 10 seconds before starting the upload
    await asyncio.sleep(10)

    # Upload based on the user preference
    if upload_destination == "playerx":
        file_size = round(os.path.getsize(output_file) / (1024 * 1024), 2)  # MB, rounded to 2 decimal places
        chunk_size = round(file_size / 10, 2)  # Assuming the file is uploaded in 10 parts, rounded to 2 decimal places

        for attempt in range(1, MAX_RETRIES + 1):
            uploaded_size = 0  # Reset uploaded size for each attempt
            start_upload_time = time.time()

            try:
                with open(output_file, "rb") as f:
                    for i in range(10):
                        uploaded_size += chunk_size
                        elapsed_time = time.time() - start_upload_time
                        speed = uploaded_size / elapsed_time if elapsed_time > 0 else 0
                        eta = int((file_size - uploaded_size) / speed) if speed > 0 else 0

                        last_update_time, last_message_content = await update_progress_message(
                            progress_message, "Uploading", filename, uploaded_size, file_size, speed, eta, last_update_time, last_message_content
                        )
                        await asyncio.sleep(1)  # Simulate time delay for each chunk upload

                    files = {'files[]': f}
                    data = {
                        'api_key': PLAYERX_API_KEY,
                        'action': 'upload_video',
                        'raw': 0
                    }
                    response = requests.post(PLAYERX_API_URL, files=files, data=data)
                    response_json = response.json()

                    if response_json.get('status') == 'success':
                        slug = response_json.get('slug')
                        await message.reply_text(f"Link: {slug}\nFilename: {filename}\nRipped by: @{user}")
                        break
                    else:
                        await message.reply_text(f"Upload failed (Attempt {attempt}/{MAX_RETRIES}). Retrying...")
            except Exception as e:
                await message.reply_text(f"Error during upload (Attempt {attempt}/{MAX_RETRIES}). Retrying... Error: {str(e)}")
            
            if attempt < MAX_RETRIES:
                await asyncio.sleep(5)  # Wait for 5 seconds before retrying

        else:
            await message.reply_text("Upload failed after maximum retries.")
            return

    else:
        file_size = os.path.getsize(output_file)
        uploaded_size = 0  # Initialize uploaded size
        start_upload_time = time.time()
        last_update_time = 0
        last_message_content = ""

        async def progress_callback(current, total):
            nonlocal uploaded_size, last_update_time, last_message_content
            uploaded_size = current / (1024 * 1024)  # Convert bytes to MB
            elapsed_time = time.time() - start_upload_time
            speed = uploaded_size / elapsed_time if elapsed_time > 0 else 0
            eta = int((file_size - current) / speed) if speed > 0 else 0

            last_update_time, last_message_content = await update_progress_message(
                progress_message, "Uploading to Telegram", filename, uploaded_size, file_size / (1024 * 1024), speed, eta, last_update_time, last_message_content
            )

        # Upload video as a video, not GIF
        await app.send_video(
            message.chat.id,
            output_file,
            caption=f"Filename: {filename}\nRipped by: @{user}",
            supports_streaming=True,
            progress=progress_callback
        )

    await progress_message.delete()

    # Clean up the system by removing the file
    if os.path.exists(output_file):
        os.remove(output_file)

# Function to handle downloading and uploading via yt-dlp with progress bar
async def handle_download(message: Message, url, user, upload_destination, output_file):
    progress_message = await message.reply_text(f"Starting downloading of {output_file}...")

    # yt-dlp download with progress
    def progress_hook(d):
        if d['status'] == 'downloading':
            downloaded_bytes = d['downloaded_bytes'] / (1024 * 1024)  # Convert to MB
            total_bytes = d.get('total_bytes', 0) / (1024 * 1024)  # Convert to MB
            eta = d.get('eta', 0)
            speed = d.get('speed', 0) / (1024 * 1024)  # Convert to MB/s

            nonlocal last_update_time, last_message_content
            last_update_time, last_message_content = asyncio.run_coroutine_threadsafe(
                update_progress_message(
                    progress_message, "Downloading", output_file, downloaded_bytes, total_bytes, speed, eta, last_update_time, last_message_content
                ), asyncio.get_event_loop()
            ).result()

    ydl_opts = {
        'outtmpl': output_file,
        'format': 'best',
        'progress_hooks': [progress_hook],
    }

    last_update_time = 0
    last_message_content = ""

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    # Handle the upload after downloading
    await handle_recording(message, output_file, "00:00:00", output_file, user, upload_destination, [""])

    # Clean up the system by removing the file
    if os.path.exists(output_file):
        os.remove(output_file)

# Command to delete specific file types
@app.on_message(filters.command("delete") & filters.user(SUDO_USERS))
async def delete_files(client, message: Message):
    file_types = ["*.mp4", "*.mkv", "*.png", "*.jpg", "*.ts", "*.m3u8", "*.ogg"]
    deleted_files = []

    for file_type in file_types:
        for file in glob.glob(file_type):
            try:
                os.remove(file)
                deleted_files.append(file)
            except Exception as e:
                await message.reply_text(f"Error deleting {file}: {str(e)}")

    if deleted_files:
        await message.reply_text(f"Deleted files:\n" + "\n".join(deleted_files))
    else:
        await message.reply_text("No files found to delete.")

# Command to execute a shell command
@app.on_message(filters.command("shell") & filters.user(SUDO_USERS))
async def execute_shell_command(client, message: Message):
    command = message.text.split(" ", 1)[1]  # Get the command after "/shell"

    try:
        output = subprocess.check_output(command, shell=True, stderr=subprocess.STDOUT, universal_newlines=True)
        if len(output) > 4096:  # If the output is too long, save it to a file
            output_file = "shell_output.txt"
            with open(output_file, "w") as f:
                f.write(output)
            await app.send_document(message.chat.id, output_file)
            os.remove(output_file)
        else:
            await message.reply_text(f"Command output:\n{output}")
    except subprocess.CalledProcessError as e:
        await message.reply_text(f"Command failed with error:\n{e.output}")

# Command to retrieve log files
@app.on_message(filters.command("log") & filters.user(SUDO_USERS))
async def get_logs(client, message: Message):
    command_parts = message.text.split()
    days = int(command_parts[1]) if len(command_parts) > 1 else 1  # Default to 1 day

    log_files = []
    for i in range(days):
        log_file = f"log_{i}.txt"  # Assuming log files are named like "log_0.txt", "log_1.txt", etc.
        if os.path.exists(log_file):
            log_files.append(log_file)
    
    if log_files:
        for log_file in log_files:
            await app.send_document(message.chat.id, log_file)
    else:
        await message.reply_text("No logs found.")

# Command to start the bot and send a welcome message to admin
@app.on_message(filters.command("start"))
async def start(client, message: Message):
    user = message.from_user.id
    if user in SUDO_USERS:
        await message.reply_text("Hi! Welcome admin!")
    else:
        await message.reply_text("Unauthorized. This bot is for admins only.")

# Command to record a stream
@app.on_message(filters.command("record"))
async def record(client, message: Message):
    logging.info("Received /record command")
    
    if message.from_user.id not in SUDO_USERS and message.chat.id != AUTHORIZED_GROUP:
        await message.reply_text("You are not authorized to use this command.")
        return
    
    command = message.text.split()
    if len(command) < 4:
        await message.reply_text("Incorrect syntax. Use /record <m3u8 url> <HH:MM:SS> <name> <language1> <language2> ...")
        return

    m3u8_url, duration, filename = command[1], command[2], command[3]
    audio_languages = command[4:]
    user = message.from_user.username
    
    # Get the user's preferred upload destination
    upload_destination = user_settings.get(user, "playerx")
    
    # Start the recording in a separate asyncio task
    asyncio.create_task(handle_recording(message, m3u8_url, duration, filename, user, upload_destination, audio_languages))

# Command to set default upload destination
@app.on_message(filters.command("set"))
async def set_upload_destination(client, message: Message):
    logging.info("Received /set command")
    
    if message.from_user.id not in SUDO_USERS and message.chat.id != AUTHORIZED_GROUP:
        await message.reply_text("You are not authorized to use this command.")
        return
    
    command = message.text.split()
    if len(command) != 2 or command[1] not in ["video", "playerx"]:
        await message.reply_text("Incorrect syntax. Use /set <video/playerx>")
        return

    user = message.from_user.username
    user_settings[user] = command[1]
    await message.reply_text(f"Default upload destination set to {command[1]}")

# Command to download a video via yt-dlp and upload
@app.on_message(filters.command("dl"))
async def download_video(client, message: Message):
    logging.info("Received /dl command")

    if message.from_user.id not in SUDO_USERS:
        await message.reply_text("You are not authorized to use this command.")
        return

    command = message.text.split()
    if len(command) < 2:
        await message.reply_text("Incorrect syntax. Use /dl <link> [--title <filename>]")
        return

    url = command[1]
    if "--title" in command:
        title_index = command.index("--title") + 1
        if title_index < len(command):
            output_file = command[title_index]
        else:
            await message.reply_text("You must specify a filename after '--title'.")
            return
    else:
        output_file = "downloaded_video.mkv"

    user = message.from_user.username
    
    # Get the user's preferred upload destination
    upload_destination = user_settings.get(user, "playerx")
    
    # Start the download and upload in a separate asyncio task
    asyncio.create_task(handle_download(message, url, user, upload_destination, output_file))

# Start the bot
if __name__ == "__main__":
    logging.info("Starting the bot")
    app.run()
