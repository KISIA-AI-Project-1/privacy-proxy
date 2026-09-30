import asyncio

import httpx


async def run_test():
    url = "http://localhost:8000/v1/chat"

    headers = {"Authorization": "Bearer example-proxy-key"}

    # OpenAI 대신 제미나이 규격으로 요청을 보냅니다. (L2 어댑터가 이를 감지해 Gemini로 연결함)
    payload = {
        "model": "gemini-pro",
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


asyncio.run(run_test())
