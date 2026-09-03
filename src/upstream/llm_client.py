# import google.generativeai as genai  # 실제 API 연동 시 사용할 구글 공식 라이브러리
from privacy_proxy.schemas import ProxyContext

PRIVACY_SYSTEM_SKILL = """
# System Skill: Privacy Token Preservation
당신은 개인정보 보호 프록시(Privacy Proxy)를 통해 대화하는 AI 어시스턴트입니다.
사용자의 질문에는 `<PHONE_1>`, `<LOC_1>`과 같은 가명화(Anonymized) 토큰이 포함되어 있습니다.

##  CRITICAL RULES (절대 규칙)
- `< >`로 둘러싸인 토큰의 형태를 **절대** 변경하지 마십시오.
- 토큰 내부에 띄어쓰기를 추가하거나, 소문자로 변경하거나, 번역하지 마십시오.
- 답변 생성 시 문맥에 맞게 토큰을 배치하되, 반드시 입력받은 원본 형태 그대로 출력해야 합니다.
"""


async def call_gemini_l7(context: ProxyContext) -> ProxyContext:
    """
    [L7 레이어] 가명화된 텍스트를 Gemini API에 전송하고 원시 답변을 받아옵니다.
    """
    if context.status == "failed":
        return context

    try:
        # 2. 보낼 데이터 준비: L6에서 만든 '별명으로 치환된 텍스트'를 꺼냄
        # (만약 치환할 개인정보가 없었다면 원본 텍스트를 그대로 사용)
        prompt_to_send = context.anonymized_prompt or context.raw_prompt

        # --- [실제 Gemini 통신 코드] ---
        # model = genai.GenerativeModel('gemini-1.5-flash')
        # response = await model.generate_content_async(prompt_to_send)
        # context.llm_raw_response = response.text

        # --- [임시 테스트용 통신] ---
        #  AWS 세팅이 끝나기 전까지 흉내
        print(f"[L7] Gemini로 데이터 전송 중... (내용: {prompt_to_send})")

        # 가상의 AI 답변을 스키마의 'llm_raw_response' 필드에 저장
        context.llm_raw_response = (
            f"[AI의 가상 답변입니다] 요청하신 내용을 잘 받았습니다. "
            f"전달받은 문장: '{prompt_to_send}'"
        )

    except Exception as e:
        context.status = "failed"
        context.error = f"L7 Gemini API 통신 실패: {e!s}"

    return context
