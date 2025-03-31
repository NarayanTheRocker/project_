import json
import requests
# from groq import Groq # Assuming Groq is still needed for the core AI
from groq import Groq # Keep Groq if you are using it for the AI model
from datetime import datetime
import os
import speech_recognition as sr
# import pygame # No longer needed for server-side playback
import edge_tts
import asyncio
import io
from flask import Flask, request, jsonify, render_template, Response, session
from dotenv import load_dotenv
import functools # For async wrapper
from pydub import AudioSegment

# --- Flask App Setup ---
app = Flask(__name__)

# --- Configuration and Constants ---
MEMORY_FILE = "memory.json" # Assuming memory is still used
# TASKS_FILE = "tasks.json" # Not used in provided snippet
# WARDROBE_FILE = "wardrobe.json" # --- REMOVED ---
LATITUDE = 17.6868 # Replace with your actual latitude
LONGITUDE = 83.2185 # Replace with your actual longitude
TMDB_API_KEY = "eyJhbGciOiJIUzI1NiJ9.eyJhdWQiOiI0MGUzZmJjNjgxMGI4NmQ4ODYxZjQ0OTExNTE1MDViZiIsIm5iZiI6MTc0MjI3MDc4My45OTUwMDAxLCJzdWIiOiI2N2Q4ZjEzZjU2MmU4MzJjOTczNjU0NWYiLCJzY29wZXMiOlsiYXBpX3JlYWQiXSwidmVyc2lvbiI6MX0.nObMMUtgNNXWwlR8Eh-B5hDeZRdI9ObcLpEwCCmLSGc" 
GROQ_API_KEY = "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"

# Ensure API keys are loaded
if not TMDB_API_KEY:
    print("Warning: TMDB_API_KEY not found in environment variables. Movie functionality may fail.")
if not GROQ_API_KEY:
    print("Error: GROQ_API_KEY not found in environment variables. AI functionality will fail.")
    # Consider exiting if Groq is essential: sys.exit("Groq API Key missing.")

# --- Existing Functions (Weather, Movies, Memory, Time - Mostly Unchanged) ---

def get_weather():
    # ... (get_weather function remains the same) ...
    url = f"https://api.open-meteo.com/v1/forecast?latitude={LATITUDE}&longitude={LONGITUDE}&daily=temperature_2m_max,temperature_2m_min,precipitation_sum&current_weather=true&timezone=auto"
    try:
        response = requests.get(url)
        response.raise_for_status() # Check for HTTP errors
        data = response.json()

        current_weather = data.get("current_weather", {})
        daily_data = data.get("daily", {})

        temp = current_weather.get("temperature", "N/A")
        weather_code = current_weather.get("weathercode", -1)
        rain_chance = daily_data.get("precipitation_sum", [None])[0] # Today's rain chance
        temp_max = daily_data.get("temperature_2m_max", [None])[0]
        temp_min = daily_data.get("temperature_2m_min", [None])[0]

        weather_conditions = {
            0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
            45: "Fog", 48: "Rime fog", 51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
            61: "Light rain", 63: "Moderate rain", 65: "Heavy rain", 71: "Light snow", 73: "Moderate snow",
            75: "Heavy snow", 80: "Light showers", 81: "Moderate showers", 82: "Heavy showers",
            95: "Thunderstorms", 96: "Thunderstorms with hail"
        }
        weather = weather_conditions.get(weather_code, "Unknown")

        # Handle potential None values if API response is partial
        rain_chance = rain_chance if rain_chance is not None else "N/A"
        temp_max = temp_max if temp_max is not None else "N/A"
        temp_min = temp_min if temp_min is not None else "N/A"


        return temp, weather, rain_chance, temp_max, temp_min

    except requests.exceptions.RequestException as e:
        print(f"Error fetching weather: {e}")
        return "Unavailable", "Unavailable", "Unavailable", "Unavailable", "Unavailable"
    except Exception as e:
        print(f"Error processing weather data: {e}")
        return "Error", "Error", "Error", "Error", "Error"


def get_movies(query, platform=None):
    # ... (get_movies function remains the same) ...
    if not TMDB_API_KEY:
        return ["Error: TMDB API Key not configured"]

    url = f"https://api.themoviedb.org/3/search/movie?api_key={TMDB_API_KEY}&query={query}&language=en-US"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        movies_data = data.get("results", [])

        # Note: Filtering by platform based on title/overview might be unreliable
        # Consider using the TMDB /discover endpoint with watch providers if needed
        if platform:
            platform_lower = platform.lower()
            movies = [m for m in movies_data if platform_lower in m.get("title", "").lower() or platform_lower in m.get("overview", "").lower()]
        else:
             movies = movies_data # Use all results if no platform specified


        # Return titles of the top 4 relevant movies
        return [m.get("title", "Unknown Title") for m in movies[:4]]

    except requests.exceptions.RequestException as e:
        print(f"Error fetching movies: {e}")
        return ["Error fetching movie data"]
    except Exception as e:
        print(f"Error processing movie data: {e}")
        return ["Error processing movie data"]


def load_memory():
    # Consider using Flask sessions for better multi-user support
    # return session.get('conversation_history', [])
    # Sticking to file-based for simplicity as per original code:
    try:
        if os.path.exists(MEMORY_FILE):
            with open(MEMORY_FILE, "r") as f:
                return json.load(f)
        return []
    except (json.JSONDecodeError, IOError) as e:
        print(f"Error loading memory file: {e}. Starting fresh.")
        return []

def save_memory(conversation_history):
    # session['conversation_history'] = conversation_history
    try:
        with open(MEMORY_FILE, "w") as f:
            json.dump(conversation_history, f, indent=2)
    except IOError as e:
        print(f"Error saving memory file: {e}")


# def load_wardrobe(): # --- REMOVED ---
#     pass # Function removed


def get_current_time():
    return datetime.now().strftime("%A, %d %B %Y, %I:%M %p")

# --- Modified/New Functions for Web ---

def run_async(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        return asyncio.run(func(*args, **kwargs))
    return wrapper

# --- MODIFIED: Default gender set to male ---
async def generate_speech_data(text, gender='male'): # Default set to male
    voice = "en-IN-PrabhatNeural"  # Default to male voice
    if gender == 'female':         # Switch to female only if requested
        voice = "en-IN-NeerjaNeural"

    communicate = edge_tts.Communicate(text, voice, rate="+10%") # You can adjust rate
    audio_data = b""
    try:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_data += chunk["data"]
        return audio_data
    except Exception as e:
        print(f"❌ Error in TTS generation: {e}")
        return None

def recognize_audio_data(audio_data):
    """Recognizes speech from audio data bytes. Handles WebM conversion."""
    # ... (recognize_audio_data function remains the same) ...
    recognizer = sr.Recognizer()
    try:
        # Convert WebM to WAV if necessary
        audio_segment = AudioSegment.from_file(io.BytesIO(audio_data), format="webm")
        wav_data = io.BytesIO()
        audio_segment.export(wav_data, format="wav")
        wav_data.seek(0) #reset the position of the file object

        with sr.AudioFile(wav_data) as source:
            print("🎙️ Processing received audio...")
            audio = recognizer.record(source)
            user_text = recognizer.recognize_google(audio)
            print(f"Recognized Text: {user_text}")
            return user_text

    except sr.UnknownValueError:
        print("Could not understand audio.")
        return None
    except sr.RequestError as e:
        print(f"Could not request results from Google Speech Recognition service; {e}")
        return None
    except Exception as e:
        print(f"Error processing audio data: {e}")
        return None


# --- Groq Client and Initial Data Loading ---
try:
    client = Groq(api_key=GROQ_API_KEY)
except Exception as e:
    print(f"Error initializing Groq client: {e}")
    client = None

# wardrobe = load_wardrobe() # --- REMOVED ---
# wardrobe_str = json.dumps(wardrobe, indent=2) # --- REMOVED ---

# --- MODIFIED: Character Profile (Wardrobe Removed) ---
def get_character_profile():
    # Removed wardrobe loading and references
    return f"""
You are Naru a supportive big brother, always warm and caring, like family and you like sarcastic and speak Hindi  .
If asked about weather, give a helpful answer using the provided data.
Give short and quick answer dont give long response.
If suggesting something (e.g., movies), LIST ONLY 4 items.
Talk like an Indian. Try to make the communication funny/sarcastic.
If User ask for Fashion suggestion: Suggest cloths considering the temperature. also add ascessories if it is required.
Keep it simple, don’t repeat yourself, and sound natural.
""" 

# --- Flask Routes ---

@app.route('/')
def index():
    """Renders the main chat page."""
    return render_template('index.html')

@app.route('/chat', methods=['POST'])
def chat_handler():
    """Handles incoming chat messages (text or references to voice)."""
    if not client:
        return jsonify({"error": "AI Client not initialized. Check API Key."}), 500

    data = request.json
    user_input = data.get('message')
    input_mode = data.get('input_mode', 'text')
    voice_gender = data.get('voice_gender', 'male') # Defaulting here is good client-side backup

    if not user_input:
        return jsonify({"error": "No message provided"}), 400

    conversation_history = load_memory()

    # --- Get Context ---
    temp, weather, rain_chance, temp_max, temp_min = get_weather()
    current_time = get_current_time()
    character_profile = get_character_profile() # Gets profile without wardrobe

    # --- Prepare messages for Groq ---
    system_prompt = (
        f"{character_profile}\n" # Wardrobe info removed from profile
        f"Current Time: {current_time}\n"
        f"Current Temperature: {temp}°C\nWeather: {weather}\n"
        f"Chance of rain tomorrow: {rain_chance} mm\nMax temperature: {temp_max}°C\nMin temperature: {temp_min}°C"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        *conversation_history,
        {"role": "user", "content": user_input}
    ]

    try:
        # --- Call Groq API ---
        completion = client.chat.completions.create(
            model="llama3-70b-8192", # Or your preferred model
            messages=messages,
            temperature=0.7,
            max_tokens=500,
        )
        ai_response_text = completion.choices[0].message.content
        ai_response_text = ai_response_text.replace('*', '') # Keep this if needed

        # --- Update and Save History ---
        conversation_history.append({"role": "user", "content": user_input})
        conversation_history.append({"role": "assistant", "content": ai_response_text})
        save_memory(conversation_history)

        # --- Generate Speech ---
        # Uses voice_gender from request, function defaults to male if not provided
        audio_data = asyncio.run(generate_speech_data(ai_response_text, voice_gender))

        print(f"🤖 Bhai (Console Output): {ai_response_text}")

        if audio_data:
            print(f"🗣️ Sending audio response ({len(audio_data)} bytes) with text header.")
            response = Response(audio_data, mimetype='audio/mpeg')
            sanitized_text_for_header = ai_response_text.replace('\n', ' ') # Handle newlines for header
            response.headers['X-Response-Text'] = sanitized_text_for_header
            return response
        else:
            print("🔊 TTS failed, sending JSON text response.")
            return jsonify({"response_text": ai_response_text})

    except Exception as e:
        print(f"Error during AI processing or TTS: {e}")
        error_message = "Sorry, I encountered an error trying to respond."
        # Try TTS for the error message itself using the requested/default gender
        error_audio = asyncio.run(generate_speech_data(error_message, voice_gender))
        if error_audio:
            # Respond with audio error if possible
             error_response = Response(error_audio, mimetype='audio/mpeg')
             error_response.headers['X-Response-Text'] = error_message # Send error text too
             return error_response, 500 # Make sure to return 500 status code
        else:
            # Fallback to JSON error
            return jsonify({"error": error_message}), 500


@app.route('/voice_input', methods=['POST'])
def voice_input_handler():
    """Handles uploaded voice data."""
    if 'audio_data' not in request.files:
        return jsonify({"error": "No audio data found"}), 400

    audio_file = request.files['audio_data']
    audio_bytes = audio_file.read()

    # Recognize speech
    user_text = recognize_audio_data(audio_bytes)

    # Get preferred voice gender for the response
    voice_gender = request.form.get('voice_gender', 'male') # Default to male if not sent with voice

    if user_text:
        # --- Refactored AI Logic (Could be moved to a shared function) ---
        if not client: return jsonify({"error": "AI Client not initialized."}), 500

        conversation_history = load_memory()
        temp, weather, rain_chance, temp_max, temp_min = get_weather()
        current_time = get_current_time()
        character_profile = get_character_profile() # Gets profile without wardrobe
        system_prompt = (
            f"{character_profile}\n"
            f"Current Time: {current_time}\n"
            f"Current Temperature: {temp}°C\nWeather: {weather}\n"
            f"Chance of rain tomorrow: {rain_chance} mm\nMax temperature: {temp_max}°C\nMin temperature: {temp_min}°C"
        )
        messages = [
            {"role": "system", "content": system_prompt},
            *conversation_history,
            {"role": "user", "content": user_text}
        ]

        try:
            completion = client.chat.completions.create(
                model="llama3-70b-8192",
                messages=messages,
                temperature=0.7,
                max_tokens=500
            )
            ai_response_text = completion.choices[0].message.content.replace('*', '')

            conversation_history.append({"role": "user", "content": user_text})
            conversation_history.append({"role": "assistant", "content": ai_response_text})
            save_memory(conversation_history)

            print(f"🤖 Bhai (Console Output): {ai_response_text}") # Log response

            # Generate audio using the requested gender
            audio_data = asyncio.run(generate_speech_data(ai_response_text, voice_gender))

            if audio_data:
                 print(f"🗣️ Sending audio response ({len(audio_data)} bytes) with text header.")
                 response = Response(audio_data, mimetype='audio/mpeg')
                 sanitized_text_for_header = ai_response_text.replace('\n', ' ')
                 response.headers['X-Response-Text'] = sanitized_text_for_header
                 return response
            else:
                 print("🔊 TTS failed, sending JSON text response.")
                 return jsonify({"response_text": ai_response_text})

        except Exception as e:
            print(f"Error during AI processing (voice input): {e}")
            error_message = "Sorry, I encountered an error."
            error_audio = asyncio.run(generate_speech_data(error_message, voice_gender))
            if error_audio:
                 error_response = Response(error_audio, mimetype='audio/mpeg')
                 error_response.headers['X-Response-Text'] = error_message
                 return error_response, 500
            else:
                 return jsonify({"error": error_message}), 500
        # --- End Refactored Logic ---

    else:
        # STT failed
        error_message = "Sorry, I couldn't understand the audio."
        print(f"👂 STT failed.")
        error_audio = asyncio.run(generate_speech_data(error_message, voice_gender))
        if error_audio:
             error_response = Response(error_audio, mimetype='audio/mpeg')
             error_response.headers['X-Response-Text'] = error_message
             return error_response, 400 # Return 400 for bad request (unintelligible audio)
        else:
             return jsonify({"error": error_message}), 400


# --- Run the App ---
if __name__ == '__main__':
    load_dotenv() # Load .env file variables
    print("Starting Flask app...")
    # --- MODIFIED: Removed wardrobe.json check ---
    print("Ensure 'memory.json' exists (or will be created).")
    print("Ensure .env file is present with API keys (GROQ_API_KEY, TMDB_API_KEY).")
    # Use debug=False for production
    app.run(debug=True, host='0.0.0.0', port=5000) # Accessible on network