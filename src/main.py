from flask import Flask
import subprocess
import os
import signal
import time
import threading

app = Flask(__name__)

# Global variable to track bot process
bot_process = None

def start_bot():
    """Start the Discord bot as a subprocess"""
    global bot_process
    try:
        # Run the original Discord bot script
        bot_process = subprocess.Popen(['python3', 'app.py'], 
                                     cwd='/home/ubuntu/discord_bot_app',
                                     stdout=subprocess.PIPE, 
                                     stderr=subprocess.PIPE)
        print(f"Discord bot started with PID: {bot_process.pid}")
    except Exception as e:
        print(f"Failed to start Discord bot: {e}")

def monitor_bot():
    """Monitor the bot process and restart if needed"""
    global bot_process
    while True:
        if bot_process is None or bot_process.poll() is not None:
            print("Bot process not running, starting...")
            start_bot()
        time.sleep(30)  # Check every 30 seconds

@app.route('/')
def home():
    global bot_process
    status = "Online" if bot_process and bot_process.poll() is None else "Offline"
    status_color = "green" if status == "Online" else "red"
    
    return f'''
    <h1>Discord Bot Hosting Service</h1>
    <p>Your Discord bot is now hosted and running 24/7.</p>
    <p>Bot Status: <span style="color: {status_color};">{status}</span></p>
    <p>Process ID: {bot_process.pid if bot_process and bot_process.poll() is None else "N/A"}</p>
    <p>The bot will automatically respond to Discord commands.</p>
    <hr>
    <h3>Available Endpoints:</h3>
    <ul>
        <li><a href="/status">/status</a> - JSON status information</li>
        <li><a href="/health">/health</a> - Health check endpoint</li>
        <li><a href="/restart">/restart</a> - Restart the bot</li>
    </ul>
    '''

@app.route('/status')
def status():
    global bot_process
    if bot_process and bot_process.poll() is None:
        return {"status": "online", "pid": bot_process.pid, "uptime": "running"}
    else:
        return {"status": "offline", "pid": None}

@app.route('/health')
def health():
    return {"status": "healthy", "service": "discord-bot-hosting"}

@app.route('/restart')
def restart():
    global bot_process
    try:
        if bot_process and bot_process.poll() is None:
            bot_process.terminate()
            bot_process.wait(timeout=10)
        start_bot()
        return {"status": "restarted", "pid": bot_process.pid if bot_process else None}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.route('/logs')
def logs():
    """Show recent bot logs"""
    try:
        with open('/home/ubuntu/discord_bot_app/app.log', 'r') as f:
            logs = f.read()
        return f"<pre>{logs}</pre>"
    except Exception as e:
        return f"Error reading logs: {e}"

if __name__ == '__main__':
    # Start the bot monitoring thread
    monitor_thread = threading.Thread(target=monitor_bot, daemon=True)
    monitor_thread.start()
    
    # Start Flask app
    app.run(host='0.0.0.0', port=5000, debug=False)

