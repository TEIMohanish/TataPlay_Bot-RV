import os
import subprocess
import requests
import asyncio
import time
import logging
from telethon import TelegramClient, events, types, errors

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

# Initialize the Telethon client
api_id = 7331082
api_hash = "5d4a78eeed44e18e97bc4ce58e397e15"
bot_token = "6009987351:AAFY8_hxgcME2yKzkFCrbITSjapw8vwweog"
client = TelegramClient("tobot", api_id, api_hash).start(bot_token=bot_token)

# Progress bar helper function
def create_progress_bar(current, total, length=20):
    progress = int((current / total) * length)
    bar = f"[{'●' * progress}{'○' * (length - progress)}]"
    return bar

# Function to update progress on the same message
async def update_progress_message(message, phase, filename, current, total, speed, eta, last_update_time, last_message_content):
    if time.time() - last_update_time < 5:
        return last_update_time, last_message_content

    r = 'Sec' if phase in ['Recording'] else 'MB'
    progress_bar = create_progress_bar(current, total)
    current_rounded = round(current, 2)
    total_rounded = round(total, 2)
    new_message_content = (
        f"[+] {phase}\n"
        f" {filename}\n"
        f"{progress_bar} \n"
        f"Process: {round((current / total) * 100, 2)}%\n"
        f"{current_rounded}{r} of {total_rounded}{r}\n"
        f"ETA: {eta}s"
    )
    
    if new_message_content != last_message_content:
        try:
            await message.edit(new_message_content)
            last_message_content = new_message_content
        except errors.FloodWaitError as e:
            logging.warning(f"Flood wait error: Sleeping for {e.seconds} seconds")
            await asyncio.sleep(e.seconds)
        except errors.MessageNotModifiedError:
            logging.info("Message content was not modified, skipping edit.")

    return time.time(), last_message_content

# Function to handle recording and uploading
async def handle_recording(event, m3u8_url, duration, filename, user, upload_destination):
    output_file = f"{filename}.mp4"
    total_duration = int(duration.split(':')[0]) * 3600 + int(duration.split(':')[1]) * 60 + int(duration.split(':')[2])
    
    # Start the initial message
    progress_message = await event.reply(f"Starting recording of {filename}...")

    # Record the stream using ffmpeg
    try:
        start_time = time.time()
        ffmpeg_command = [
            "ffmpeg", "-y", "-i", m3u8_url,
            "-t", duration, "-c", "copy", output_file
        ]

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
            await event.reply("Recording failed.")
            return

    except Exception as e:
        await event.reply(f"Recording failed. Error: {str(e)}")
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
                        await event.reply(f"Link: {slug}\nFilename: {filename}\nRipped by: @{user}")
                        break
                    else:
                        await event.reply(f"Upload failed (Attempt {attempt}/{MAX_RETRIES}). Retrying...")
            except Exception as e:
                await event.reply(f"Error during upload (Attempt {attempt}/{MAX_RETRIES}). Retrying... Error: {str(e)}")
            
            if attempt < MAX_RETRIES:
                await asyncio.sleep(5)  # Wait for 5 seconds before retrying

        else:
            await event.reply("Upload failed after maximum retries.")
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
        attributes = [types.DocumentAttributeVideo(duration=total_duration, w=1920, h=1080, round_message=False, supports_streaming=True)]
        await client.send_file(
            event.chat_id,
            output_file,
            caption=f"Filename: {filename}\nRipped by: @{user}",
            attributes=attributes,
            progress_callback=progress_callback
        )

    await progress_message.delete()

    # Delete the local file
    if os.path.exists(output_file):
        os.remove(output_file)

# Command to start the bot and send a welcome message to admin
@client.on(events.NewMessage(pattern="/start"))
async def start(event):
    user = event.sender_id
    if event.is_private:
        if user in SUDO_USERS:
            await event.reply("Hi! Welcome admin!")
        else:
            await event.reply("Unauthorized. This bot is for admins only.")
            return
    else:
        await event.reply("Hi! How can I assist you today?")

# Command to record a stream
@client.on(events.NewMessage(pattern="/record"))
async def record(event):
    logging.info("Received /record command")
    
    if event.is_private:
        if event.sender_id not in SUDO_USERS:
            await event.reply("You are not authorized to use this command in private chat.")
            return
    elif event.chat_id == AUTHORIZED_GROUP:
        # Allow group members to use the command
        pass
    else:
        await event.reply("This command can only be used in the authorized group.")
        return
    
    command = event.raw_text.split()
    if len(command) != 4:
        await event.reply("Incorrect syntax. Use /record <m3u8 url> <HH:MM:SS> <name>")
        return

    m3u8_url, duration, filename = command[1], command[2], command[3]
    user = event.sender.username
    
    # Get the user's preferred upload destination
    upload_destination = user_settings.get(user, "playerx")
    
    # Start the recording in a separate asyncio task
    asyncio.create_task(handle_recording(event, m3u8_url, duration, filename, user, upload_destination))

# Command to set default upload destination
@client.on(events.NewMessage(pattern="/set"))
async def set_upload_destination(event):
    logging.info("Received /set command")
    
    if event.is_private:
        if event.sender_id not in SUDO_USERS:
            await event.reply("You are not authorized to use this command in private chat.")
            return
    elif event.chat_id == AUTHORIZED_GROUP:
        # Allow group members to use the command
        pass
    else:
        await event.reply("This command can only be used in the authorized group.")
        return
    
    command = event.raw_text.split()
    if len(command) != 2 or command[1] not in ["video", "playerx"]:
        await event.reply("Incorrect syntax. Use /set <video/playerx>")
        return

    user = event.sender.username
    user_settings[user] = command[1]
    await event.reply(f"Default upload destination set to {command[1]}")

# Start the bot
if __name__ == "__main__":
    logging.info("Starting the bot")
    client.run_until_disconnected()

