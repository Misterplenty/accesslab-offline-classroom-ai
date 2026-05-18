# Safety Boundaries & Best Practices

AccessLab is designed to be a safe, offline-first classroom AI assistant. It provides a controlled environment for educators and students to interact with generative AI locally.

## Local Data And Privacy

- **100% Data Privacy:** All teacher-uploaded materials and student interactions are stored locally on the host device.
- **Role-Based Views:** AccessLab provides distinct views for learners, teachers, and admins to simplify the classroom experience.
- **Offline First:** No cloud services are required, ensuring that classroom data never leaves the local network.

## Grounded Answers

- **Retrieval-Augmented Generation (RAG):** AccessLab uses local search to find answers directly within teacher-uploaded materials before asking Gemma 4 to synthesize a response.
- **Curriculum Alignment:** By grounding answers in specific documents, AccessLab ensures that students receive information aligned with their curriculum.
- **Honest AI:** AccessLab is designed to rely heavily on provided context, reducing the likelihood of hallucinations.

## Local Model Runtime

- **Independent Execution:** All AI models run locally via Ollama, ensuring high performance without internet dependencies.
- **Transparent Status:** The system provides clear indicators of model readiness and availability.

## Python Runner

- **Educational Sandbox:** The code tutor runs beginner Python snippets locally to help students learn debugging interactively.
- **Constructive Feedback:** Instead of just giving the answer, the code tutor diagnoses errors and provides minimal, educational patches to guide students.

## Local / School-Box Scope

- **Classroom Scalability:** School-box mode allows a single local machine to host AccessLab for nearby classroom browsers over a local area network (LAN), making it incredibly easy to deploy in disconnected environments.
