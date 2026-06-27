# SAIP v2.5 — Stock_analysis_Intelligence_platform

AI-powered multi-agent stock analysis pipeline with 10 agents, evidence auditing,
Bull vs Bear debate, and CIO multidimensional output.

## Quick Start

```bash
# 1. Clone and setup
git clone <repo>
cd hedge-fund-app

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set up environment variables
cp .env.example .env
# Edit .env with your API keys:
# - GEMINI_API_KEY (for fallback tier 4)
# - OPENAI_API_KEY (optional)
# - ANTHROPIC_API_KEY (optional)
# - OLLAMA_BASE_URL (default: http://localhost:11434)
# - OLLAMA_OFFICE_MODEL (default: qwen2.5-14b)

# 4. Pull Ollama models (optional, for local fallbacks)
ollama pull qwen2.5-14b
ollama pull deepseek-v4-pro
ollama pull glm-5.2

# 5. Run analysis
python src/main.py --ticker RELIANCE.NS --exchange IN --duration 18

# Or run with JSON output
python src/main.py --ticker TCS.NS --exchange IN --duration 18 --format json --output report.json

# Quick mode (faster, fewer agents)
python src/main.py --ticker INFY.NS --exchange IN --depth quick

# Skip debate for faster execution
python src/main.py --ticker HDFCBANK.NS --exchange IN --no-debate
```

## Model Cascade (4-Tier)

Each agent tries models in this order:

| Tier | Type | Example |
|------|------|---------|
| 1 | Primary (original default) | `deepseek-v4-pro`, `kimi-k2.5` |
| 2 | Fallback 1 (original fallback) | `glm-5.2`, `gpt-oss-120b` |
| 3 | Fallback 2 (Ollama local) | `qwen2.5-14b` (office model) |
| 4 | Fallback 3 (Gemini API) | `gemini-2.5-flash` |

Configure the office model in `.env`:
```
OLLAMA_OFFICE_MODEL=qwen2.5-14b
```

## Streamlit Dashboard

```bash
streamlit run app.py
```

## Testing

```bash
pytest tests/ -v
```

## Architecture

- **Stage 1**: Intelligence Builder (Yahoo Finance + News + Regime data)
- **Stage 2**: 6 Parallel Specialist Agents
- **Stage 3**: Evidence Auditor (validates all reports)
- **Stage 4**: Bull vs Bear Debate (8 rounds + Committee Q&A)
- **Stage 5**: CIO Judgment (multidimensional output)

See `SIAP_v2_ARCHITECTURE.md` for full details.
