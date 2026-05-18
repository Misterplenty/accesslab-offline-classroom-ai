# AccessLab: Offline Classroom AI

AccessLab is an offline-first, local classroom AI assistant powered by **Gemma 4** and **Ollama**. It is designed to bring the power of generative AI to classrooms with limited or no internet connectivity, while ensuring 100% data privacy.

AccessLab runs entirely on local hardware, grounding its answers securely in teacher-uploaded materials and helping students learn Python coding interactively.

Primary Focus: **Future of Education**  
Core Technology: **Gemma 4 & Ollama**  
Key Themes: **Digital Equity, Inclusivity, and Data Privacy**

---

## 🚀 Live Demo

Experience AccessLab directly in your browser:

- **Interactive Demo:** [https://mrinference-accesslab-gemma4.hf.space/judge-demo](https://mrinference-accesslab-gemma4.hf.space/judge-demo)
- **System Proofs:** [https://mrinference-accesslab-gemma4.hf.space/proofs](https://mrinference-accesslab-gemma4.hf.space/proofs)
- **Health Check API:** [https://mrinference-accesslab-gemma4.hf.space/healthz](https://mrinference-accesslab-gemma4.hf.space/healthz)

---

## ✨ Key Features

- **Grounded Q&A:** Upload TXT, MD, or PDF materials. AccessLab uses Retrieval-Augmented Generation (RAG) to provide citation-backed answers directly from the curriculum.
- **Python Code Tutor:** Students can submit broken Python snippets. AccessLab runs the code locally, diagnoses the error, provides a minimal educational patch, and verifies the fix.
- **Hybrid Search:** Combines SQLite FTS5 (Lexical) and EmbeddingGemma (Semantic) to accurately retrieve relevant classroom context.
- **Teacher Dashboard:** Educators can review class activity, inspect Q&A sessions, and monitor what students are struggling with.
- **100% Local & Private:** No API keys, no cloud dependencies. Everything runs locally on your machine.

---

## 💻 Quickstart (Local Setup)

To run AccessLab on your own hardware, you will need Python 3.10+ and [Ollama](https://ollama.com) installed.

**1. Clone and Install Dependencies:**
```bash
git clone https://github.com/Misterplenty/accesslab-offline-classroom-ai.git
cd accesslab-offline-classroom-ai
python3 -m venv .venv
source .venv/bin/activate
make install
cp .env.example .env
```

**2. Start Ollama & Pull Models:**
In a separate terminal, ensure Ollama is running and download the required Gemma 4 models:
```bash
ollama serve
ollama pull gemma4:e4b
ollama pull gemma4:e2b
ollama pull embeddinggemma
```

**3. Launch the Application:**
You can launch the app with pre-seeded demonstration data:
```bash
make judge-demo
```
Then open `http://127.0.0.1:8000/judge-demo` in your browser.

Alternatively, to start a fresh instance:
```bash
make run-strong
```

---

## 🏗️ Architecture & Stack

| Component | Technology | Purpose |
| --- | --- | --- |
| **Backend** | FastAPI (Python) | High-performance async API and routing |
| **LLM Engine** | Ollama | Local execution of Gemma 4 |
| **Retrieval (RAG)**| SQLite FTS5 + EmbeddingGemma | Fast hybrid search for grounding answers |
| **Frontend** | Jinja2 + Vanilla CSS/JS | Lightweight, accessible, and responsive UI |
| **Code Runner** | Local Subprocess Execution | Safely tests beginner Python snippets |

---

## 📚 Documentation

Detailed documentation on the architecture, setup, and evaluation metrics can be found in the repository:

- [Demo Runbook](docs/demo_runbook.md)
- [Hugging Face Space Setup](docs/huggingface_space.md)
- [System Preflight & Proofs](proofs/manifest.md)
- [Safety Boundaries](docs/safety_boundaries.md)

---

## 📄 License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
