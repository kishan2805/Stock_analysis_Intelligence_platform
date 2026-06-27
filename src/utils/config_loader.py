import os
import yaml
from dotenv import load_dotenv
from types import SimpleNamespace


class ConfigNamespace(SimpleNamespace):
    """SimpleNamespace subclass that also supports mapping .get(key, default).

    This preserves attribute-style access while allowing callers that expect a
    dict-like `get` method to continue working without changes.
    """

    def get(self, key, default=None):
        return getattr(self, key, default)


def _dict_to_namespace(d):
    if isinstance(d, dict):
        return ConfigNamespace(**{k: _dict_to_namespace(v) for k, v in d.items()})
    elif isinstance(d, list):
        return [_dict_to_namespace(i) for i in d]
    return d

def load_config(path: str = "config/settings.yaml"):
    load_dotenv()
    with open(path, "r") as f:
        raw = yaml.safe_load(f)

    # Resolve env vars
    def resolve_env(val):
        if isinstance(val, str) and val.startswith("${") and val.endswith("}"):
            env_key = val[2:-1]
            return os.getenv(env_key, "")
        return val

    def resolve_dict(d):
        if isinstance(d, dict):
            return {k: resolve_dict(v) for k, v in d.items()}
        elif isinstance(d, list):
            return [resolve_dict(i) for i in d]
        return resolve_env(d)

    resolved = resolve_dict(raw)

    # Inject office_model into ollama config (prioritize env var if set)
    if "ollama" in resolved:
        env_office = os.getenv("OLLAMA_OFFICE_MODEL")
        if env_office:
            resolved["ollama"]["office_model"] = env_office
        elif "office_model" not in resolved["ollama"]:
            resolved["ollama"]["office_model"] = "qwen2.5-14b"

    return _dict_to_namespace(resolved)
