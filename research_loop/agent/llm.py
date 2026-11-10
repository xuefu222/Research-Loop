"""从本地配置初始化 Qwen 模型客户端。"""

from langchain.chat_models import init_chat_model

from paper_research.config import model_config


def make_model():
    config = model_config()
    if not all(
        isinstance(config.get(key), str) and config[key].strip()
        for key in ("base_url", "model", "api_key")
    ):
        raise ValueError("Set MAIN_BASE_URL, MAIN_MODEL and MAIN_API_KEY or use the local model configuration")

    # Qwen 提供 OpenAI 兼容的 Chat Completions 接口。
    return init_chat_model(
        model=config["model"],
        model_provider="openai",
        base_url=config["base_url"],
        api_key=config["api_key"],
        temperature=0,
        timeout=60,
        max_retries=0,
        disable_streaming=True,
        use_responses_api=False,
        extra_body={"max_tokens": 3500},
    )
