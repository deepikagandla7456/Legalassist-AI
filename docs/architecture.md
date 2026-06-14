# Architecture Overview

Deep dive into the architecture of the Legalassist-AI codebase.

## System Topology
- **FastAPI Backend**: Handles client API requests, user authentication, and task queuing.
- **Streamlit Frontend**: Provides an interactive dashboard for judgment Simplification.
- **Celery Task Queue**: Handles long-running PDF text extraction and LLM-based remedies analysis.
- **Chroma DB / Sharded Store**: Powers RAG search embeddings context.
