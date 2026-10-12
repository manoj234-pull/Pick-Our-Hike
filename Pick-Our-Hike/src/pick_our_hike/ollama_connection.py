"""Local service status; no model download or hosted API."""
import os
import httpx


def connection_status():
    model = os.getenv('PICK_OUR_HIKE_MODEL', 'phi4-mini')
    host = os.getenv('OLLAMA_HOST', 'http://127.0.0.1:11434').rstrip('/')
    try:
        response = httpx.get(host + '/api/tags', timeout=2, trust_env=False)
        response.raise_for_status()
        names = {item['name'] for item in response.json()['models']}
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return False, 'Open the Ollama desktop app to connect the local AI. Your draft stays here.'
    if model not in names and model + ':latest' not in names:
        return False, f'Ollama is running but {model} is not installed. The app never downloads models.'
    return True, f'Local AI connected · {model}'
