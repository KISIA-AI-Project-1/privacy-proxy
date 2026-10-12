import asyncio
import os

import httpx

from privacy_proxy.config import get_settings


async def run_test() -> None:
    url = "http://localhost:8000/v1/chat"

    api_key = get_settings().proxy_api_key.get_secret_value().strip()
    if not api_key:
        raise ValueError("PROXY_API_KEY_REQUIRED")
    headers = {"Authorization": f"Bearer {api_key}"}

    # OpenAI 대신 제미나이 규격으로 요청을 보냅니다. (L2 어댑터가 이를 감지해 Gemini로 연결함)
    payload = {
        "model": os.getenv("DEMO_MODEL", "gemini-3.1-flash-lite"),
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": "안녕하세요, 홍길동입니다. 제 번호는 010-1234-5678 인데요, 환불 언제 되나요?"
                    }
                ],
            }
        ],
    }

    print("🚀 제미나이 프록시 서버로 요청을 전송합니다...")
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers, json=payload, timeout=30.0)

        print("\n[클라이언트가 받은 최종 응답]")
        print(response.json())


if __name__ == "__main__":
    asyncio.run(run_test())
