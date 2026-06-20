_ASSETS_CHECKED = False
_MISSING_EMBEDDING_WARNED = False

from yumi.core.features.config import is_model_available, load_model_config


def assets_check(interactive: bool = False) -> bool:
    global _ASSETS_CHECKED
    global _MISSING_EMBEDDING_WARNED
    if _ASSETS_CHECKED:
        return True

    config = load_model_config()
    if not config.embedding_model:
        _ASSETS_CHECKED = True
        return False

    if config.embedding_provider != "ollama":
        _ASSETS_CHECKED = True
        return True

    try:
        if not is_model_available(config.embedding_provider, config.embedding_model):
            if interactive:
                from yumi.core.features.config.credentials import _get_provider

                provider = _get_provider("ollama")
                provider.pull_model(config.embedding_model)
            else:
                if not _MISSING_EMBEDDING_WARNED:
                    print(
                        "Embedding model is not available locally. "
                        "Memory embeddings are disabled until you run `yumi --setup` "
                        f"or install `{config.embedding_model}`."
                    )
                    _MISSING_EMBEDDING_WARNED = True
                return False
        _ASSETS_CHECKED = True
        return True
    except Exception as e:
        print(f"Ollama connection failed: {e}")
        return False
