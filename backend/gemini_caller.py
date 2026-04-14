import vertexai
from vertexai.generative_models import GenerativeModel

vertexai.init(project="pharmagraph", location="us-central1")
model = GenerativeModel("gemini-2.5-flash")

SYSTEM_PROMPT = """You are a clinical drug interaction assistant.
Answer the user's question using ONLY the context provided below.
Always cite your sources using [DrugBank], [FAERS], [SIDER], or [PMID: xxxxx].
If a known interaction exists, clearly state there is a risk and explain the mechanism.
If the context doesn't contain enough information, say so clearly and recommend consulting a healthcare provider.
Never downplay or dismiss potential drug interactions."""

def generate(query, context):
    prompt = f"""{SYSTEM_PROMPT}

{context}

User question: {query}

Answer:"""
    response = model.generate_content(prompt)
    return response.text
