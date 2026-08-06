import requests

from config import BOT_TOKEN, CHAT_ID

MAX_MESSAGE_LENGTH = 4000


def send_message(message: str):

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    for i in range(0, len(message), MAX_MESSAGE_LENGTH):

        chunk = message[i:i + MAX_MESSAGE_LENGTH]

        payload = {
            "chat_id": CHAT_ID,
            "text": chunk,
            "disable_web_page_preview": False
        }

        response = requests.post(
            url,
            json=payload,
            timeout=30
        )

        if response.status_code != 200:
            print(response.text)